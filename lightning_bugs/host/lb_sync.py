#!/usr/bin/env python3
"""
lb_sync.py — sync Lightning Bugs devices to this computer's clock over SWD.

Attaches with pyocd WITHOUT halting or resetting the core, finds the sync block
that firmware/lightning_bugs/lb_sync.h places in RAM, measures the chip's
millisecond counter against the host clock, and writes back an anchor, a
clock-rate correction and a shared beat grid.

Commands
  list                     show connected debug probes
  sync                     measure clock rate (default 10 min) and write the sync
  sync --refine            re-sync using the time since the last sync as a long
                           baseline for the rate (best accuracy; see README)
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
import math
import statistics
import sys
import time
from dataclasses import dataclass

# ─── Block layout (must match LbSyncBlock in lb_sync.h) ──────────────────────
MAGIC0 = 0x4C425359                      # 'LBSY'
MAGIC1 = MAGIC0 ^ 0xFFFFFFFF
VERSION = 1
RAM_BASE = 0x20000000
RAM_SIZE = 8 * 1024

BLOCK_FIELDS = [
    "magic0", "magic1", "version", "tick_addr", "seq", "ack_seq", "hold",
    "anchor_tick", "anchor_us_lo", "anchor_us_hi", "corr_ppb",
    "epoch_us_lo", "epoch_us_hi", "period_us",
]
W = {name: i for i, name in enumerate(BLOCK_FIELDS)}
BLOCK_WORDS = len(BLOCK_FIELDS)

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
        self.addr = self._find_block()
        blk = self.read_block()
        if blk.version != VERSION:
            raise SyncError(f"sync block version {blk.version}, this script speaks {VERSION}")
        if not (RAM_BASE <= blk.tick_addr < RAM_BASE + RAM_SIZE):
            raise SyncError(f"tick_addr 0x{blk.tick_addr:08x} is not in RAM")
        self.tick_addr = blk.tick_addr

    def _find_block(self) -> int:
        words = self.t.read_memory_block32(RAM_BASE, RAM_SIZE // 4)
        hits = [RAM_BASE + 4 * i for i in range(len(words) - BLOCK_WORDS)
                if words[i] == MAGIC0 and words[i + 1] == MAGIC1
                and words[i + W["version"]] == VERSION]
        if not hits:
            raise SyncError("no Lightning Bugs sync block in RAM — is lb_sync.h firmware flashed and running?")
        if len(hits) > 1:
            raise SyncError("multiple sync-block candidates in RAM: " + ", ".join(f"0x{a:08x}" for a in hits))
        return hits[0]

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
    if args.period_ms is not None:
        period_us = round(args.period_ms * 1000)
    else:
        period_us = round(60e6 / args.bpm)
    if period_us <= 0:
        raise SyncError("beat period must be positive")
    return round(args.epoch * 1e6), period_us


def cmd_sync(dev: Device, args, log=print) -> dict:
    epoch_us, period_us = grid_from_args(args)
    prev = dev.read_block()
    long_slope = None

    if args.refine:
        if not prev.synced:
            raise SyncError("--refine needs a previous sync on this device (run plain `sync` first)")
        mean, sd, _ = measure_offset(dev, prev)
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
    return {"anchor_tick": anchor_tick, "anchor_us": anchor_us, "corr_ppb": corr,
            "epoch_us": epoch_us, "period_us": period_us, "seq": seq}


def cmd_status(dev: Device, args, log=print) -> dict:
    blk = dev.read_block()
    log(f"Sync block at 0x{blk.addr:08x}, tick @ 0x{blk.tick_addr:08x}, hold={blk.hold}")
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
    session = ConnectHelper.session_with_chosen_probe(
        unique_id=args.probe, blocking=False, options=options)
    if session is None:
        raise SyncError("no debug probe found (try `list`, or pass --probe)")
    return session


def run_with_device(args, fn):
    deadline = time.monotonic() + (args.wait if getattr(args, "wait", 0) else 0)
    while True:
        try:
            with open_session(args) as session:
                target = session.board.target
                if getattr(args, "reset", False):
                    target.reset()           # software reset → firmware re-enters boot guard
                    time.sleep(0.3)
                return fn(Device(target), args)
        except Exception as e:               # retry while waiting for a power-cycle (--wait)
            if time.monotonic() >= deadline:
                if isinstance(e, SyncError):
                    raise
                raise SyncError(f"SWD connection failed: {e}")
            time.sleep(0.2)


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
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list debug probes")

    sp = sub.add_parser("sync", help="measure and write a sync")
    sp.add_argument("--duration", type=float, help="sampling time in s (default 600, or 30 with --refine)")
    sp.add_argument("--interval", type=float, default=5.0, help="seconds between samples (default 5)")
    sp.add_argument("--burst", type=int, default=8, help="reads per sample; fastest is kept (default 8)")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--bpm", type=float, default=120.0, help="beat tempo (default 120)")
    g.add_argument("--period-ms", type=float, help="beat period in ms instead of --bpm")
    sp.add_argument("--epoch", type=float, default=0.0,
                    help="Unix time of beat 0 (default 0; keep identical on every device)")
    sp.add_argument("--refine", action="store_true",
                    help="use time since the previous sync as the rate baseline")
    sp.add_argument("--min-refine", type=float, default=600, help="minimum baseline for --refine, s")
    sp.add_argument("--horizon", type=float, default=6.0, help="hours to project drift over (default 6)")

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
        else:
            fn = {"sync": cmd_sync, "status": cmd_status, "hold": cmd_hold, "release": cmd_release}[args.cmd]
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
