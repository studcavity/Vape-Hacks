#!/usr/bin/env python3
"""
lb_sync.py — sync Lightning Bugs devices to this computer's clock over SWD.

Attaches with pyocd WITHOUT halting or resetting the core, finds the sync block
that firmware/lightning_bugs/lb_sync.h places in RAM, measures the chip's
millisecond counter against the host clock, and writes back an anchor, a
clock-rate correction and a shared beat grid.

Commands
  list                     show connected debug probes
  info                     firmware version, build and wire format of the connected
                           unit; works even if the unit's format is not one this
                           script speaks
  sync                     measure clock rate (default 10 min) and write the sync
  sync --refine            re-sync using the time since the last sync as a long
                           baseline for the rate (best accuracy; see README)
  resync                   quick (~15 s) re-sync for a device you plug in every
                           hour or so: the previous anchor is the baseline, the
                           grid is kept, and the visit is logged with the
                           device UID and its temperature (see README)
  report                   per-device and all-device drift statistics from the log
  status                   report how far the device has drifted from this host
  hold [--reset|--wait]    keep the device parked in its boot guard (SWD safe)
  release                  let a held device continue booting

Every device synced against an NTP-disciplined computer shares one timeline:
beat n happens at Unix time  epoch + n * period,  so devices can be synced one
at a time with a single probe, even on different days.

Requires: pip install pyocd   (plus the Puya pack providing target py32f030x8)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ─── Block layout (must match LbSyncBlock in lb_sync.h) ──────────────────────
# The first HEADER_WORDS words never move or change meaning, so any host can find a block
# and report what it is. Format compatibility: a different MAJOR is a different layout; a
# MINOR only appends words at the end, so a unit with the same major and a minor at least
# as high as ours has every field we use.
MAGIC0 = 0x4C425359                      # 'LBSY'
MAGIC1 = MAGIC0 ^ 0xFFFFFFFF
FORMAT_MAJOR = 4
FORMAT_MINOR = 0
HEADER_WORDS = 8
RAM_BASE = 0x20000000
RAM_SIZE = 8 * 1024

BLOCK_FIELDS = [
    "magic0", "magic1", "format", "block_words", "fw_version", "fw_build", "fw_flags", "tick_addr",
    "seq", "ack_seq", "hold",
    "anchor_tick", "anchor_us_lo", "anchor_us_hi", "corr_ppb",
    "epoch_us_lo", "epoch_us_hi", "period_us",
    "uid0", "uid1", "uid2", "uid3",
    "temp_cdeg", "temp_min_cdeg", "temp_max_cdeg", "temp_sum_cdeg", "temp_n",
    "temp_raw", "vref_raw", "stats_tick",
    "batt_mv", "power_state", "wake_count",
]
W = {name: i for i, name in enumerate(BLOCK_FIELDS)}
BLOCK_WORDS = len(BLOCK_FIELDS)

NO_TEMP = -(1 << 31)                     # LB_NO_TEMP in lb_sync.h
MAX_CORR_PPB = 50_000_000                # 5 %: anything bigger is not a real HSI error
U32 = 1 << 32


class SyncError(Exception):
    pass


# ─── Small helpers ────────────────────────────────────────────────────────────
def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - U32 if v & 0x80000000 else v


def s64(lo: int, hi: int) -> int:
    v = (hi << 32) | lo
    return v - (1 << 64) if v & (1 << 63) else v


def c_div(a: int, b: int) -> int:
    """Integer division truncating toward zero, like C."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def device_master_us(blk: "Block", tick: int) -> int:
    """Exactly what lbMasterUs() computes on the device for a given millis()."""
    L = s32(tick - blk.anchor_tick)
    return blk.anchor_us + L * 1000 + c_div(L * blk.corr_ppb, 1_000_000)


@dataclass
class Block:
    addr: int
    words: list

    def __getattr__(self, name):
        if name in W:
            return self.words[W[name]]
        raise AttributeError(name)

    @property
    def anchor_us(self) -> int:
        return s64(self.anchor_us_lo, self.anchor_us_hi)

    @property
    def epoch_us(self) -> int:
        return s64(self.epoch_us_lo, self.epoch_us_hi)

    @property
    def corr_ppb(self) -> int:
        return s32(self.words[W["corr_ppb"]])

    @property
    def synced(self) -> bool:
        return self.ack_seq != 0 and self.ack_seq == self.seq

    @property
    def version_text(self) -> str:
        return describe_header(parse_header(self.words))

    @property
    def uid_bytes(self) -> bytes:
        return b"".join(self.words[W[f"uid{i}"]].to_bytes(4, "little") for i in range(4))

    @property
    def uid(self) -> str:
        """Full chip UID as 32 hex digits; empty if the firmware has not written one."""
        b = self.uid_bytes
        return b.hex() if any(b) else ""

    @property
    def short_uid(self) -> str:
        """Wafer number and die X/Y (UID bytes 4 and 8-11): what tells units from one batch apart."""
        b = self.uid_bytes
        return b[4:5].hex() + "-" + b[8:12].hex() if any(b) else "?"

    def temperature(self) -> dict | None:
        """Temperature stats since the last adopted sync, in degC; None if there is no reading."""
        t = s32(self.words[W["temp_cdeg"]])
        if t == NO_TEMP:
            return None
        n = self.words[W["temp_n"]]
        out = {"now_c": t / 100, "n": n, "raw": self.temp_raw, "vref_raw": self.vref_raw}
        if n:
            out.update(min_c=s32(self.words[W["temp_min_cdeg"]]) / 100,
                       max_c=s32(self.words[W["temp_max_cdeg"]]) / 100,
                       mean_c=s32(self.words[W["temp_sum_cdeg"]]) / n / 100)
        return out


@dataclass
class Header:
    """The fixed first words of a sync block, parsed; valid for any format, including ones we cannot speak."""
    addr: int
    legacy: bool            # a pre-header layout (formats 1-3): only the format number is known
    major: int
    minor: int
    block_words: int | None
    fw: tuple | None        # (major, minor, patch)
    build: int | None       # git commit prefix; 0 = unknown
    dirty: bool
    tick_addr: int


def parse_header(words, addr: int = 0) -> Header:
    """Words 0..7 of a block. Formats 1-3 had a bare small integer in word 2 and the tick address in word 3."""
    if words[2] < 0x10000:
        return Header(addr, True, words[2], 0, None, None, None, False, words[3])
    f = words[W["fw_version"]]
    return Header(addr, False, words[2] >> 16, words[2] & 0xFFFF, words[W["block_words"]],
                  (f >> 16 & 0xFF, f >> 8 & 0xFF, f & 0xFF), words[W["fw_build"]],
                  bool(words[W["fw_flags"]] & 1), words[W["tick_addr"]])


def describe_header(h: Header) -> str:
    if h.legacy:
        return f"wire format {h.major} (older than version reporting; firmware version unknown)"
    fw = ".".join(str(n) for n in h.fw)
    build = f"build {h.build:08x}{'+dirty' if h.dirty else ''}" if h.build else "build unknown"
    return f"firmware {fw} ({build}), wire format {h.major}.{h.minor}"


def check_compatible(h: Header) -> None:
    ours = f"{FORMAT_MAJOR}.{FORMAT_MINOR}"
    if h.legacy or h.major != FORMAT_MAJOR:
        raise SyncError(f"this unit runs {describe_header(h)}, but this script speaks {ours}. "
                        "Reflash the unit with the current firmware, or use a lb_sync.py from the same release.")
    if h.minor < FORMAT_MINOR:
        raise SyncError(f"this unit runs {describe_header(h)}, older than {ours}: it lacks fields this "
                        "script needs. Reflash it with the current firmware.")
    if h.block_words is None or h.block_words < BLOCK_WORDS:
        raise SyncError(f"this unit's sync block is {h.block_words} words; this script needs {BLOCK_WORDS} "
                        f"({describe_header(h)})")
    if not (RAM_BASE <= h.tick_addr < RAM_BASE + RAM_SIZE):
        raise SyncError(f"tick_addr 0x{h.tick_addr:08x} is not in RAM")


def find_blocks(target) -> list:
    """Headers of every sync block in RAM, of any format (found by the two magic words alone)."""
    words = target.read_memory_block32(RAM_BASE, RAM_SIZE // 4)
    return [parse_header(words[i:i + HEADER_WORDS], RAM_BASE + 4 * i)
            for i in range(len(words) - HEADER_WORDS)
            if words[i] == MAGIC0 and words[i + 1] == MAGIC1]


class HostClock:
    def mono_ns(self) -> int:
        return time.monotonic_ns()

    def wall_ns(self) -> int:
        return time.time_ns()

    def sleep(self, s: float) -> None:
        time.sleep(s)


def wall_minus_mono_ns(clock) -> int:
    best = None
    for _ in range(9):
        m0 = clock.mono_ns()
        w = clock.wall_ns()
        m1 = clock.mono_ns()
        if best is None or (m1 - m0) < best[0]:
            best = (m1 - m0, w - (m0 + m1) // 2)
    return best[1]


# ─── Device access ───────────────────────────────────────────────────────────
@dataclass
class Sample:
    x_ns: int      # host monotonic ns at the middle of the read
    tick: int      # raw 32-bit device millis()
    rtt_ns: int    # round trip of that read


class Device:
    def __init__(self, target, clock=None):
        self.t = target
        self.clock = clock or HostClock()
        found = find_blocks(target)
        if not found:
            raise SyncError("no Lightning Bugs sync block in RAM — is lb_sync.h firmware flashed and running?")
        if len(found) > 1:
            raise SyncError("multiple sync-block candidates in RAM: " + ", ".join(f"0x{h.addr:08x}" for h in found))
        self.header = found[0]
        check_compatible(self.header)
        self.addr = self.header.addr
        self.tick_addr = self.header.tick_addr

    def read_block(self) -> Block:
        return Block(self.addr, list(self.t.read_memory_block32(self.addr, BLOCK_WORDS)))

    def write(self, field: str, value: int) -> None:
        self.t.write32(self.addr + 4 * W[field], value & 0xFFFFFFFF)

    def sample(self, burst: int = 8) -> Sample:
        """Best-of-N read of the tick counter; keeps the shortest round trip."""
        best = None
        for _ in range(burst):
            t0 = self.clock.mono_ns()
            tick = self.t.read32(self.tick_addr)
            t1 = self.clock.mono_ns()
            if best is None or (t1 - t0) < best.rtt_ns:
                best = Sample((t0 + t1) // 2, tick, t1 - t0)
        return best

    def write_sync(self, anchor_tick: int, anchor_us: int, corr_ppb: int,
                   epoch_us: int, period_us: int, ack_timeout_s: float = 3.0) -> int:
        seq = self.read_block().seq
        writing = (seq + 1) | 1                     # odd: firmware ignores the block
        final = (writing + 1) & 0xFFFFFFFF or 2     # even, never 0
        self.write("seq", writing)
        self.write("anchor_tick", anchor_tick)
        self.write("anchor_us_lo", anchor_us & 0xFFFFFFFF)
        self.write("anchor_us_hi", (anchor_us >> 32) & 0xFFFFFFFF)
        self.write("corr_ppb", corr_ppb)
        self.write("epoch_us_lo", epoch_us & 0xFFFFFFFF)
        self.write("epoch_us_hi", (epoch_us >> 32) & 0xFFFFFFFF)
        self.write("period_us", period_us)
        self.write("seq", final)
        deadline = self.clock.mono_ns() + int(ack_timeout_s * 1e9)
        while self.clock.mono_ns() < deadline:
            if self.read_block().ack_seq == final:
                return final
            self.clock.sleep(0.05)
        raise SyncError("firmware did not acknowledge the sync (is it calling lbMasterUs()/lbPoll()?)")


# ─── Measurement and fitting ─────────────────────────────────────────────────
@dataclass
class Fit:
    x0_ns: int          # host monotonic origin
    tick0: int          # raw device tick origin (y is relative to this)
    slope: float        # device ms per host second
    xm: float           # mean x (s) of kept samples
    ym: float           # mean y (device ms, tick-centered) of kept samples
    resid_ms: float     # RMS residual
    slope_se: float     # standard error of slope
    n: int
    span_s: float

    @property
    def ppm(self) -> float:
        return (self.slope / 1000.0 - 1.0) * 1e6


def fit_samples(samples: list[Sample]) -> Fit:
    if len(samples) < 3:
        raise SyncError("need at least 3 samples")
    x0, t0 = samples[0].x_ns, samples[0].tick
    pts = [((s.x_ns - x0) / 1e9, ((s.tick - t0) % U32) + 0.5, s.rtt_ns) for s in samples]

    # Drop reads with unusually slow round trips, then refit without 3σ outliers.
    med_rtt = statistics.median(p[2] for p in pts)
    pts = [p for p in pts if p[2] <= 3 * med_rtt] or pts

    def ols(ps):
        n = len(ps)
        xm = sum(p[0] for p in ps) / n
        ym = sum(p[1] for p in ps) / n
        sxx = sum((p[0] - xm) ** 2 for p in ps)
        if sxx == 0:
            raise SyncError("samples have no time spread")
        b = sum((p[0] - xm) * (p[1] - ym) for p in ps) / sxx
        res = [p[1] - (ym + b * (p[0] - xm)) for p in ps]
        dof = max(n - 2, 1)
        sigma = math.sqrt(sum(r * r for r in res) / dof)
        return xm, ym, b, res, sigma, sxx

    xm, ym, b, res, sigma, sxx = ols(pts)
    if len(pts) > 6 and sigma > 0:
        kept = [p for p, r in zip(pts, res) if abs(r) <= 3 * sigma]
        if len(kept) >= 3:
            pts = kept
            xm, ym, b, res, sigma, sxx = ols(pts)

    return Fit(x0, t0, b, xm, ym, sigma, sigma / math.sqrt(sxx), len(pts),
               pts[-1][0] - pts[0][0])


def collect(dev: Device, duration_s: float, interval_s: float, burst: int,
            log=print) -> list[Sample]:
    clock = dev.clock
    n_points = max(3, int(round(duration_s / interval_s)) + 1)
    start = clock.mono_ns()
    samples: list[Sample] = []
    for i in range(n_points):
        target = start + int(i * interval_s * 1e9)
        wait = (target - clock.mono_ns()) / 1e9
        if wait > 0:
            clock.sleep(wait)
        samples.append(dev.sample(burst))
        if i == 1:
            dt = (samples[1].x_ns - samples[0].x_ns) / 1e9
            rate = ((samples[1].tick - samples[0].tick) % U32) / dt
            if not 900 <= rate <= 1100:
                raise SyncError(f"tick counter runs at {rate:.0f}/s, expected ~1000/s — wrong tick_addr?")
        if i >= 2 and (i % max(1, n_points // 20) == 0 or i == n_points - 1):
            f = fit_samples(samples)
            log(f"  [{i + 1:4d}/{n_points}] {f.span_s:7.1f}s  rate {f.ppm:+9.1f} ppm"
                f"  ±{f.slope_se / f.slope * 1e6:6.2f} ppm  rtt {samples[-1].rtt_ns / 1e6:5.2f} ms")
    return samples


def compute_sync(fit: Fit, wall_off_ns: int, slope: float | None = None):
    """Return (anchor_tick, anchor_us, corr_ppb) anchored at the samples' centroid."""
    b = slope if slope is not None else fit.slope
    corr = round((1000.0 / b - 1.0) * 1e9)
    if abs(corr) > MAX_CORR_PPB:
        raise SyncError(f"measured clock error {corr / 1e7:+.2f}% is implausible; not writing")
    anchor_rel = math.floor(fit.ym - 0.5)                 # integer tick near the centroid
    x_star = fit.xm + (anchor_rel + 0.5 - fit.ym) / b     # host s when device is mid-tick
    anchor_tick = (fit.tick0 + anchor_rel) % U32
    anchor_us = round((fit.x0_ns + x_star * 1e9 + wall_off_ns) / 1000)
    return anchor_tick, anchor_us, corr


def measure_offset(dev: Device, blk: Block, n: int = 10, burst: int = 8):
    """Mean (device master − host wall) in ms over n samples."""
    off = wall_minus_mono_ns(dev.clock)
    vals = []
    for _ in range(n):
        s = dev.sample(burst)
        host_us = (s.x_ns + off) / 1000
        vals.append((device_master_us(blk, s.tick) - host_us) / 1000)
        dev.clock.sleep(0.1)
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0), s


# ─── Commands ────────────────────────────────────────────────────────────────
def grid_from_args(args):
    if getattr(args, "every", None) is not None:
        period_us = round(args.every * 1e6)
    elif args.period_ms is not None:
        period_us = round(args.period_ms * 1000)
    else:
        period_us = round(60e6 / args.bpm)
    if period_us >= U32:
        raise SyncError("beat/show period must be under 71 minutes (it is stored in 32 bits of µs)")
    if period_us <= 0:
        raise SyncError("beat period must be positive")
    return round(args.epoch * 1e6), period_us


def cmd_sync(dev: Device, args, log=print) -> dict:
    epoch_us, period_us = grid_from_args(args)
    prev = dev.read_block()
    long_slope = None
    elapsed_s = drift_ms = None

    if args.refine:
        if not prev.synced:
            raise SyncError("--refine needs a previous sync on this device (run plain `sync` first)")
        mean, sd, _ = measure_offset(dev, prev)
        drift_ms = mean
        log(f"Drift since last sync: {mean:+.1f} ms (±{sd:.1f})")

    duration = args.duration if args.duration is not None else (30 if args.refine else 600)
    log(f"Sampling for {duration:.0f} s every {args.interval:g} s ...")
    samples = collect(dev, duration, args.interval, args.burst, log)
    fit = fit_samples(samples)
    wall_off = wall_minus_mono_ns(dev.clock)

    if args.refine:
        # Device ms elapsed between old anchor (mid-tick) and the new centroid,
        # over host wall time elapsed between the same two moments.
        d_rel = ((fit.tick0 - prev.anchor_tick) % U32) + fit.ym - 0.5
        w_us = (fit.x0_ns + fit.xm * 1e9 + wall_off) / 1000
        elapsed_s = (w_us - prev.anchor_us) / 1e6
        if elapsed_s < args.min_refine:
            raise SyncError(f"only {elapsed_s:.0f} s since the last sync; need {args.min_refine:.0f} s "
                            "for a useful long baseline")
        long_slope = d_rel / elapsed_s
        log(f"Long-baseline clock rate over {elapsed_s / 3600:.2f} h: {(long_slope / 1000 - 1) * 1e6:+.2f} ppm "
            f"(short window: {fit.ppm:+.1f} ppm fast; previous correction {prev.corr_ppb / 1000:+.2f} ppm)")

    anchor_tick, anchor_us, corr = compute_sync(fit, wall_off, long_slope)
    seq = dev.write_sync(anchor_tick, anchor_us, corr, epoch_us, period_us)

    h = args.horizon
    # Long baseline: rate error ≈ (~2 ms anchor/offset uncertainty) / elapsed time.
    rel_se = fit.slope_se / fit.slope if long_slope is None else 0.002 / elapsed_s
    log(f"\nSynced (seq {seq}).  rate correction {corr / 1000:+.2f} ppm, residual {fit.resid_ms:.2f} ms RMS")
    log(f"Beat grid: {60e6 / period_us:.3f} BPM, epoch {epoch_us / 1e6:.3f}")
    log(f"Measurement-limited drift over {h:g} h: ±{rel_se * h * 3600 * 1000:.0f} ms (1σ)")
    log("Temperature and supply-voltage changes usually dominate; check with `status` later.")
    rec = visit_record("sync", prev, fit, corr, long_slope, args, elapsed_s, drift_ms)
    rec.update({"anchor_tick": anchor_tick, "anchor_us": anchor_us, "corr_ppb": corr,
                "epoch_us": epoch_us, "period_us": period_us, "seq": seq})
    return rec


def temp_text(t: dict | None) -> str:
    if not t:
        return "no reading yet"
    s = f"{t['now_c']:.1f} °C now"
    if "mean_c" in t:
        s += f"; since last sync min {t['min_c']:.1f} / mean {t['mean_c']:.1f} / max {t['max_c']:.1f} (n={t['n']})"
    return s


def vcc_mv(blk: Block) -> int | None:
    """Battery voltage in mV as the firmware last measured it (VDD is the cell); None if never read."""
    return blk.batt_mv or None


def power_text(blk: Block) -> str:
    mv = vcc_mv(blk)
    s = f"{mv / 1000:.3f} V" if mv else "battery not read yet"
    s += f"; USB input {'high' if blk.power_state & 2 else 'low'}"
    if blk.power_state & 1:
        s += "; LOW-BATTERY LATCHED (will sleep after its 60 s window)"
    if blk.wake_count:
        s += f"; woken from sleep {blk.wake_count}x since boot"
    return s


def visit_record(kind: str, prev: Block, fit: Fit, corr_ppb: int, long_slope: float | None,
                 args, elapsed_s: float | None = None, drift_ms: float | None = None) -> dict:
    """One line of the visit log: what the device looked like when it was plugged in."""
    rate_slope = long_slope if long_slope is not None else fit.slope
    rec = {
        "kind": kind,
        "wall_s": round(time.time(), 3),
        "uid": prev.uid, "short_uid": prev.short_uid,
        "fw": ".".join(str(n) for n in parse_header(prev.words).fw),
        "fw_build": f"{prev.fw_build:08x}" if prev.fw_build else "",
        "fw_dirty": bool(prev.fw_flags & 1),
        "format": f"{prev.format >> 16}.{prev.format & 0xFFFF}",
        "prev_synced": prev.synced,
        "rate_source": "long" if long_slope is not None else "short",
        "raw_rate_ppm": round((rate_slope / 1000.0 - 1.0) * 1e6, 3),   # device clock error, + = fast
        "prev_corr_ppb": prev.corr_ppb if prev.synced else None,
        "applied_corr_ppb": corr_ppb,
        "vcc_mv": vcc_mv(prev),
        "low_battery": bool(prev.power_state & 1),
        "usb_input": bool(prev.power_state & 2),
        "wake_count": prev.wake_count,
        "temp": prev.temperature(),
    }
    if elapsed_s is not None:
        rec["elapsed_s"] = round(elapsed_s, 3)
    if drift_ms is not None:
        rec["drift_ms"] = round(drift_ms, 3)                 # offset found before re-syncing, + = device ahead
        if elapsed_s:
            rec["residual_ppm"] = round(drift_ms / 1000 / elapsed_s * 1e6, 3)
    return rec


def cmd_resync(dev: Device, args, log=print) -> dict:
    """Quick re-sync for a device that has been running since a previous sync.

    The previous anchor, held in the device's RAM, is the baseline: the clock
    rate over the whole interval since then (typically an hour: ~0.5 ppm
    resolution) replaces a long measurement. The beat grid is kept unless a new
    one is given.
    """
    prev = dev.read_block()
    log(f"Device {prev.short_uid}  (UID {prev.uid or 'not reported'}); {prev.version_text}")
    if not prev.synced:
        if args.no_fallback:
            raise SyncError("device is not synced (power-cycled?); run a full `sync`")
        log("Not synced (power-cycled or new firmware): falling back to a full sync "
            f"({args.full_duration:.0f} s).")
        explicit = any(getattr(args, k, None) is not None for k in ("bpm", "period_ms", "every"))
        full = argparse.Namespace(
            duration=args.full_duration, interval=5.0, burst=args.burst, refine=False,
            min_refine=600, horizon=1.0,
            every=args.every, bpm=args.bpm if args.bpm is not None else 120.0,
            period_ms=(args.period_ms if explicit else (prev.period_us / 1000 or None)),
            epoch=(args.epoch if args.epoch is not None else prev.epoch_us / 1e6))
        return cmd_sync(dev, full, log)

    log(f"Previous state: {temp_text(prev.temperature())}")
    log(f"Power: {power_text(prev)}")
    if prev.power_state & 1:
        log("  WARNING: battery is low; this unit will go to sleep. Charge it, then resync.")
    drift, sd, last = measure_offset(dev, prev, n=args.offset_samples)
    log(f"Drift since last sync: {drift:+.1f} ms (±{sd:.1f}); positive = device ahead")

    samples = collect(dev, args.duration, args.interval, args.burst, log=lambda *a: None)
    fit = fit_samples(samples)
    wall_off = wall_minus_mono_ns(dev.clock)
    d_rel = ((fit.tick0 - prev.anchor_tick) % U32) + fit.ym - 0.5
    w_us = (fit.x0_ns + fit.xm * 1e9 + wall_off) / 1000
    elapsed_s = (w_us - prev.anchor_us) / 1e6

    if elapsed_s >= args.min_baseline:
        long_slope, source = d_rel / elapsed_s, "long"
        raw_ppm = (long_slope / 1000 - 1) * 1e6
        log(f"Clock rate over the last {elapsed_s / 3600:.2f} h: {raw_ppm:+.2f} ppm "
            f"(previous correction {prev.corr_ppb / 1000:+.2f} ppm)")
        step = abs(raw_ppm + prev.corr_ppb / 1000)
        if step > args.warn_ppm:
            log(f"  note: rate moved {step:.0f} ppm since the last sync (temperature or supply change?)")
    else:
        # Too soon for a useful baseline: keep the old rate and only fix the offset.
        long_slope, source = 1000.0 / (1 + prev.corr_ppb / 1e9), "kept"
        log(f"Only {elapsed_s:.0f} s since the last sync (< {args.min_baseline:.0f} s): keeping the previous rate.")

    anchor_tick, anchor_us, corr = compute_sync(fit, wall_off, long_slope)
    epoch_us = round(args.epoch * 1e6) if args.epoch is not None else prev.epoch_us
    if args.every is not None or args.period_ms is not None or args.bpm is not None:
        _, period_us = grid_from_args(args)
    else:
        period_us = prev.period_us
    seq = dev.write_sync(anchor_tick, anchor_us, corr, epoch_us, period_us)
    log(f"Resynced (seq {seq}): rate correction {corr / 1000:+.2f} ppm; grid every {period_us / 1e6:g} s")

    rec = visit_record("resync", prev, fit, corr, long_slope if source == "long" else None, args,
                       elapsed_s=elapsed_s, drift_ms=drift)
    rec.update({"rate_source": source, "seq": seq, "epoch_us": epoch_us, "period_us": period_us,
                "anchor_tick": anchor_tick, "anchor_us": anchor_us, "corr_ppb": corr})
    if source == "kept":
        rec["raw_rate_ppm"] = None
    return rec


def cmd_info(target, args, log=print) -> None:
    """What is this unit running? Works with any wire format, including ones this script cannot speak."""
    found = find_blocks(target)
    if not found:
        raise SyncError("no Lightning Bugs sync block in RAM (not running this firmware, or asleep/held in reset?)")
    for h in found:
        log(f"Sync block at 0x{h.addr:08x}: {describe_header(h)}")
        try:
            check_compatible(h)
            log(f"  compatible with this lb_sync.py (speaks wire format {FORMAT_MAJOR}.{FORMAT_MINOR})")
        except SyncError:
            log(f"  NOT compatible with this lb_sync.py (speaks wire format {FORMAT_MAJOR}.{FORMAT_MINOR}): reflash the unit")
        if not h.legacy and h.build == 0:
            log("  (built outside tools/lb_flash.py: no git commit stamped in)")


def cmd_status(dev: Device, args, log=print) -> dict:
    blk = dev.read_block()
    log(f"Sync block at 0x{blk.addr:08x}, tick @ 0x{blk.tick_addr:08x}, hold={blk.hold}")
    log(f"Device {blk.short_uid}  (UID {blk.uid or 'not reported'}); {blk.version_text}")
    log(f"Temperature: {temp_text(blk.temperature())}")
    log(f"Power: {power_text(blk)}")
    if not blk.synced:
        log("Not synced." + (f" (seq {blk.seq}, ack {blk.ack_seq})" if blk.seq else ""))
        return {"synced": False}
    mean, sd, s = measure_offset(dev, blk, n=args.samples)
    since_s = s32(s.tick - blk.anchor_tick) / 1000
    log(f"Synced {since_s / 3600:.2f} h ago; rate correction {blk.corr_ppb / 1000:+.2f} ppm; "
        f"{60e6 / blk.period_us:.3f} BPM")
    log(f"Offset vs this host: {mean:+.1f} ms (±{sd:.1f}); positive = device ahead")
    if since_s > 60:
        log(f"Residual rate since sync: {mean / 1000 / since_s * 1e6:+.2f} ppm")
    return {"synced": True, "offset_ms": mean, "since_s": since_s}


def cmd_hold(dev: Device, args, log=print):
    dev.write("hold", 1)
    log("Hold set: device stays in its boot guard (center LEDs lit) until `release` or reflash.")


def cmd_release(dev: Device, args, log=print):
    dev.write("hold", 0)
    log("Released.")


# ─── Visit log and drift report ──────────────────────────────────────────────
DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "lb_sync_log.jsonl"


def append_log(path, rec: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_log(path) -> list[dict]:
    recs = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                raise SyncError(f"{path}:{n}: not valid JSON")
    return recs


def ols(xs, ys):
    """(slope, intercept) of the least-squares line, or None if x has no spread."""
    n = len(xs)
    if n < 2:
        return None
    xm, ym = sum(xs) / n, sum(ys) / n
    sxx = sum((x - xm) ** 2 for x in xs)
    if sxx < 1e-9:
        return None
    b = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / sxx
    return b, ym - b * xm


def _stats(vals):
    return (statistics.mean(vals), statistics.stdev(vals) if len(vals) > 1 else 0.0)


def usable_visits(recs):
    """Visits that measured the raw clock rate over a long baseline and have a temperature."""
    out = []
    for r in recs:
        t = r.get("temp") or {}
        if (r.get("rate_source") == "long" and r.get("raw_rate_ppm") is not None
                and r.get("elapsed_s") and t.get("mean_c") is not None and r.get("uid")):
            out.append(r)
    return out


def drift_report(recs: list[dict]) -> dict:
    """Per-device and pooled statistics of the raw clock rate and its temperature dependence.

    raw_rate_ppm is the device's HSI-derived clock error averaged over the time
    since its previous sync (+ = fast), independent of any correction applied.
    residual_ppm is what was left over after the correction (drift_ms/elapsed).
    """
    vis = usable_visits(recs)
    per = {}
    for r in vis:
        per.setdefault(r["uid"], []).append(r)
    devices = {}
    for uid, rs in per.items():
        rates = [r["raw_rate_ppm"] for r in rs]
        temps = [r["temp"]["mean_c"] for r in rs]
        d = {"short_uid": rs[0].get("short_uid", "?"), "visits": len(rs),
             "rate_mean_ppm": _stats(rates)[0], "rate_sd_ppm": _stats(rates)[1],
             "temp_min_c": min(temps), "temp_max_c": max(temps), "temp_mean_c": statistics.mean(temps)}
        res = [r["drift_ms"] / (r["elapsed_s"] / 3600) for r in rs if r.get("drift_ms") is not None]
        if res:
            d["residual_ms_per_h_mean"] = statistics.mean(res)
            d["residual_ms_per_h_worst"] = max(res, key=abs)
        fit = ols(temps, rates) if len(rs) >= 3 else None
        if fit:
            d["ppm_per_degc"] = fit[0]
        devices[uid] = d
    pooled = {"visits": len(vis), "devices": len(per)}
    if vis:
        rates = [r["raw_rate_ppm"] for r in vis]
        pooled["rate_mean_ppm"], pooled["rate_sd_ppm"] = _stats(rates)
        fit = ols([r["temp"]["mean_c"] for r in vis], rates)
        if fit and len(vis) >= 3:
            pooled["ppm_per_degc_all"] = fit[0]
        # Within-device slope: each device's own offset removed first, so unit-to-unit
        # differences do not masquerade as a temperature effect.
        sxy = sxx = 0.0
        for rs in per.values():
            if len(rs) < 2:
                continue
            xm = statistics.mean(r["temp"]["mean_c"] for r in rs)
            ym = statistics.mean(r["raw_rate_ppm"] for r in rs)
            for r in rs:
                dx = r["temp"]["mean_c"] - xm
                sxx += dx * dx
                sxy += dx * (r["raw_rate_ppm"] - ym)
        if sxx > 1e-9:
            pooled["ppm_per_degc_within"] = sxy / sxx
        # Spread between units: sd of per-device mean rates.
        means = [d["rate_mean_ppm"] for d in devices.values()]
        if len(means) > 1:
            pooled["between_device_sd_ppm"] = statistics.stdev(means)
    firmware = {}
    for r in recs:
        if r.get("fw"):
            key = f"{r['fw']} ({r['fw_build'] or 'build unknown'}{'+dirty' if r.get('fw_dirty') else ''}), format {r.get('format', '?')}"
            firmware[key] = firmware.get(key, 0) + 1
    return {"devices": devices, "pooled": pooled, "skipped": len(recs) - len(vis),
            "battery": battery_report(recs), "firmware": firmware}


LOW_BATT_MV = 3600       # lb_power_policy.h LB_LOW_MV: where the firmware protects the cell


def battery_report(recs: list[dict]) -> dict:
    """Per device: supply voltage trend over the logged visits and a rough time to the sleep threshold.

    The cell's voltage curve is flat through the middle of its charge, so a straight-line
    projection from a few visits is optimistic early on and pessimistic near the end.
    """
    per = {}
    for r in recs:
        if r.get("uid") and r.get("vcc_mv") and r.get("wall_s") and not r.get("usb_input"):
            per.setdefault(r["uid"], []).append((r["wall_s"], r["vcc_mv"], r.get("short_uid", "?")))
    out = {}
    for uid, pts in per.items():
        pts.sort()
        d = {"short_uid": pts[0][2], "visits": len(pts), "first_mv": pts[0][1], "last_mv": pts[-1][1],
             "span_h": (pts[-1][0] - pts[0][0]) / 3600}
        fit = ols([(t - pts[0][0]) / 86400 for t, _, _ in pts], [v for _, v, _ in pts]) if len(pts) >= 3 else None
        if fit and d["span_h"] >= 1 and fit[0] < 0:
            d["mv_per_day"] = fit[0]
            d["days_to_sleep"] = max(0.0, (pts[-1][1] - LOW_BATT_MV) / -fit[0])
        out[uid] = d
    return out


def print_battery(bat: dict, out=print) -> None:
    for _, d in sorted(bat.items()):
        line = (f"battery {d['short_uid']}: {d['last_mv'] / 1000:.3f} V now "
                f"({d['first_mv'] / 1000:.3f} V {d['span_h']:.1f} h earlier, {d['visits']} visits)")
        if "mv_per_day" in d:
            line += f"; {d['mv_per_day']:+.0f} mV/day, about {d['days_to_sleep']:.0f} days to {LOW_BATT_MV / 1000:.2f} V"
        out(line)
    if bat:
        out("")


def print_report(rep: dict, out=print) -> None:
    p = rep["pooled"]
    if rep.get("firmware"):
        out("firmware in this log: " + "; ".join(f"{k} x{n}" for k, n in sorted(rep["firmware"].items())))
        if len(rep["firmware"]) > 1:
            out("  (more than one build: drift figures may mix firmware versions)")
    print_battery(rep.get("battery", {}), out)
    if not p["visits"]:
        out("No usable visits yet (need `resync` visits with a long baseline and a temperature reading).")
        if rep["skipped"]:
            out(f"({rep['skipped']} log entries skipped: short baseline, first sync, or no temperature)")
        return
    out(f"{'device':<14}{'visits':>7}{'rate ppm (mean ± sd)':>24}{'temp °C (min–max)':>22}"
        f"{'ppm/°C':>9}{'resid ms/h (mean / worst)':>28}")
    for uid, d in sorted(rep["devices"].items()):
        slope = f"{d['ppm_per_degc']:+.1f}" if "ppm_per_degc" in d else "—"
        resid = (f"{d['residual_ms_per_h_mean']:+.0f} / {d['residual_ms_per_h_worst']:+.0f}"
                 if "residual_ms_per_h_mean" in d else "—")
        out(f"{d['short_uid']:<14}{d['visits']:>7}{d['rate_mean_ppm']:>+14.1f} ± {d['rate_sd_ppm']:<6.1f}"
            f"{d['temp_min_c']:>12.1f}–{d['temp_max_c']:<8.1f}{slope:>9}{resid:>28}")
    out(f"\nAll devices: {p['visits']} visits from {p['devices']} devices; "
        f"rate {p['rate_mean_ppm']:+.1f} ± {p['rate_sd_ppm']:.1f} ppm")
    if "between_device_sd_ppm" in p:
        out(f"  unit-to-unit spread (sd of per-device means): {p['between_device_sd_ppm']:.1f} ppm")
    if "ppm_per_degc_within" in p:
        out(f"  temperature dependence within devices: {p['ppm_per_degc_within']:+.2f} ppm/°C "
            f"(pooled, unit offsets removed)")
    if "ppm_per_degc_all" in p:
        out(f"  temperature dependence, all points together: {p['ppm_per_degc_all']:+.2f} ppm/°C")
    if rep["skipped"]:
        out(f"  ({rep['skipped']} log entries not used: short baseline, first sync, or no temperature)")


def cmd_report(args, log=print):
    path = Path(args.log)
    if not path.exists():
        raise SyncError(f"no log at {path} yet (run `resync` first)")
    rep = drift_report(load_log(path))
    print_report(rep, log)
    return rep


# ─── pyocd glue ──────────────────────────────────────────────────────────────
def open_session(args):
    try:
        from pyocd.core.helpers import ConnectHelper
    except ImportError:
        raise SyncError("pyocd is not installed: pip install pyocd")
    options = {
        "connect_mode": "attach",        # never halt or reset a running device
        "auto_unlock": False,            # never mass-erase a protected chip
        "resume_on_disconnect": True,
        "frequency": args.frequency,
        "target_override": args.target,
    }
    options.update(getattr(args, "extra_options", None) or {})
    session = ConnectHelper.session_with_chosen_probe(
        unique_id=args.probe, blocking=False, options=options)
    if session is None:
        raise SyncError("no debug probe found (try `list`, or pass --probe)")
    return session


def run_with_target(args, fn, make=lambda target: Device(target)):
    """Open the probe (retrying for --wait seconds), build the handle with `make`, run `fn(handle, args)`."""
    deadline = time.monotonic() + (args.wait if getattr(args, "wait", 0) else 0)
    while True:
        try:
            with open_session(args) as session:
                target = session.board.target
                if getattr(args, "reset", False):
                    target.reset()           # software reset → firmware re-enters boot guard
                    time.sleep(0.3)
                result = fn(make(target), args)
                if (isinstance(result, dict) and result.get("kind")
                        and not getattr(args, "no_log", False)):
                    append_log(args.log, result)
                    print(f"Logged to {args.log}")
                return result
        except Exception as e:               # retry while waiting for a power-cycle (--wait)
            if time.monotonic() >= deadline:
                if isinstance(e, SyncError):
                    raise
                raise SyncError(f"SWD connection failed: {e}")
            time.sleep(0.2)


def run_with_device(args, fn):
    return run_with_target(args, fn)


def cmd_list(args):
    try:
        from pyocd.core.helpers import ConnectHelper
    except ImportError:
        raise SyncError("pyocd is not installed: pip install pyocd")
    probes = ConnectHelper.get_all_connected_probes(blocking=False)
    if not probes:
        print("No probes found.")
    for p in probes:
        print(f"{p.unique_id}  {p.description}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", "-u", help="debug probe unique ID (see `list`)")
    ap.add_argument("--target", "-t", default="py32f030x8", help="pyocd target (default py32f030x8)")
    ap.add_argument("--frequency", "-f", type=int, default=500_000, help="SWD clock Hz (default 500000)")
    ap.add_argument("--log", default=str(DEFAULT_LOG), help=f"visit log, JSON lines (default {DEFAULT_LOG})")
    ap.add_argument("--no-log", action="store_true", help="do not append this visit to the log")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list debug probes")
    ip = sub.add_parser("info", help="firmware version and wire format of the connected unit (any format)")
    ip.add_argument("--wait", type=float, default=0, help="keep retrying the SWD connection for this many seconds")

    sp = sub.add_parser("sync", help="measure and write a sync")
    sp.add_argument("--duration", type=float, help="sampling time in s (default 600, or 30 with --refine)")
    sp.add_argument("--interval", type=float, default=5.0, help="seconds between samples (default 5)")
    sp.add_argument("--burst", type=int, default=8, help="reads per sample; fastest is kept (default 8)")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--bpm", type=float, default=120.0, help="beat tempo (default 120)")
    g.add_argument("--period-ms", type=float, help="beat period in ms instead of --bpm")
    g.add_argument("--every", type=float, help="beat/show period in seconds instead of --bpm (e.g. 3600)")
    sp.add_argument("--epoch", type=float, default=0.0,
                    help="Unix time of beat 0 (default 0; keep identical on every device)")
    sp.add_argument("--refine", action="store_true",
                    help="use time since the previous sync as the rate baseline")
    sp.add_argument("--min-refine", type=float, default=600, help="minimum baseline for --refine, s")
    sp.add_argument("--horizon", type=float, default=6.0, help="hours to project drift over (default 6)")

    rp = sub.add_parser("resync", help="quick re-sync of a device that was synced before")
    rp.add_argument("--duration", type=float, default=10.0, help="sampling time in s (default 10)")
    rp.add_argument("--interval", type=float, default=1.0, help="seconds between samples (default 1)")
    rp.add_argument("--burst", type=int, default=8, help="reads per sample; fastest is kept (default 8)")
    rp.add_argument("--offset-samples", type=int, default=5, help="reads used to measure the drift (default 5)")
    rp.add_argument("--min-baseline", type=float, default=600,
                    help="shortest time since the last sync that updates the rate, s (default 600); "
                         "closer visits only fix the offset")
    rp.add_argument("--warn-ppm", type=float, default=200,
                    help="note when the rate moved this much since the last sync (default 200)")
    rp.add_argument("--no-fallback", action="store_true", help="fail instead of doing a full sync on an unsynced device")
    rp.add_argument("--full-duration", type=float, default=600, help="fallback full-sync length, s (default 600)")
    g2 = rp.add_mutually_exclusive_group()
    g2.add_argument("--bpm", type=float, default=None, help="new beat tempo (default: keep the device's grid)")
    g2.add_argument("--period-ms", type=float, default=None, help="new beat period in ms")
    g2.add_argument("--every", type=float, default=None, help="new beat/show period in seconds")
    rp.add_argument("--epoch", type=float, default=None, help="new Unix time of beat 0 (default: keep)")

    sub.add_parser("report", help="drift statistics per device and over all devices, from the log")

    st = sub.add_parser("status", help="report drift vs this host")
    st.add_argument("--samples", type=int, default=10)

    hp = sub.add_parser("hold", help="keep the device in its boot guard")
    hp.add_argument("--reset", action="store_true", help="reset the chip first so it re-enters the guard")
    hp.add_argument("--wait", type=float, default=0,
                    help="keep retrying the SWD connection for this many seconds (power-cycle meanwhile)")
    sub.add_parser("release", help="let a held device continue")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            cmd_list(args)
        elif args.cmd == "report":
            cmd_report(args)
        elif args.cmd == "info":
            run_with_target(args, cmd_info, make=lambda target: target)
        else:
            fn = {"sync": cmd_sync, "resync": cmd_resync, "status": cmd_status,
                  "hold": cmd_hold, "release": cmd_release}[args.cmd]
            run_with_device(args, fn)
    except SyncError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
