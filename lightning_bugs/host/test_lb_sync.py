"""
Simulated-device tests for lb_sync.py. No hardware or pyocd needed:
    python3 -m unittest test_lb_sync.py
"""
import argparse
import math
import random
import tempfile
import unittest
from pathlib import Path

import lb_catalog
import lb_compat
import lb_sync as lb

BLOCK_ADDR = 0x20000400
TICK_ADDR = 0x200002F8


class FakeClock:
    """Virtual time; mono == true time, wall = mono + fixed offset."""
    def __init__(self):
        self.t_ns = 5_000_000_000
        self.wall_off = 1_763_100_000 * 10**9          # ~Nov 2025

    def mono_ns(self):
        return self.t_ns

    def wall_ns(self):
        return self.t_ns + self.wall_off

    def sleep(self, s):
        self.t_ns += int(s * 1e9)


class FakeTarget:
    """A PY32 running lb_sync.h firmware whose clock is `ppm` fast, read over a jittery probe."""
    def __init__(self, clock, ppm, rng, boot_tick=4_294_000_000,
                 uid=bytes(range(0x41, 0x51)), temp_fn=lambda t_s: 25.0,
                 fw=(0, 4, 0), build=0x1A2B3C4D, flags=0, fmt=(lb.FORMAT_MAJOR, lb.FORMAT_MINOR),
                 extra_words=0):
        self.clock, self.ppm, self.rng = clock, ppm, rng
        self.boot_ns = clock.t_ns
        self.seg_ns = clock.t_ns                        # when the current ppm took effect
        self.acc_ms = 0.0                               # device ms accumulated in earlier segments
        self.boot_tick = boot_tick                      # start near wrap to test unwrapping
        self.uid, self.temp_fn = uid, temp_fn
        self.temp_hist, self.temp_next_s = [], 1.0      # one sample per 10 s, as the firmware does
        self.ram = {}
        init = [0] * (lb.BLOCK_WORDS + extra_words)
        init[lb.W["magic0"]], init[lb.W["magic1"]] = lb.MAGIC0, lb.MAGIC1
        init[lb.W["format"]] = fmt[0] << 16 | fmt[1]
        init[lb.W["block_words"]] = lb.BLOCK_WORDS + extra_words
        init[lb.W["fw_version"]] = fw[0] << 16 | fw[1] << 8 | fw[2]
        init[lb.W["fw_build"]], init[lb.W["fw_flags"]] = build, flags
        init[lb.W["tick_addr"]] = TICK_ADDR
        init[lb.W["period_us"]] = 500_000
        for i in range(4):
            init[lb.W[f"uid{i}"]] = int.from_bytes(uid[4 * i:4 * i + 4], "little")
        init[lb.W["temp_cdeg"]] = lb_catalog.NO_TEMP & 0xFFFFFFFF
        for i, v in enumerate(init):
            self.ram[BLOCK_ADDR + 4 * i] = v

    def set_ppm(self, ppm):
        """Change the clock rate from now on without rewriting the past."""
        self.acc_ms += (self.clock.t_ns - self.seg_ns) / 1e9 * 1000 * (1 + self.ppm * 1e-6)
        self.seg_ns, self.ppm = self.clock.t_ns, ppm

    def device_ms(self):
        t = (self.clock.t_ns - self.seg_ns) / 1e9
        return self.boot_tick + self.acc_ms + t * 1000 * (1 + self.ppm * 1e-6)

    def _temp_update(self):
        now = (self.clock.t_ns - self.boot_ns) / 1e9
        while self.temp_next_s <= now:
            self.temp_hist.append(round(self.temp_fn(self.temp_next_s) * 100))
            self.temp_next_s += 10
        w = lambda name, v: self.ram.__setitem__(BLOCK_ADDR + 4 * lb.W[name], v & 0xFFFFFFFF)  # noqa: E731
        if self.temp_hist:
            h = self.temp_hist
            w("temp_cdeg", h[-1]); w("temp_min_cdeg", min(h)); w("temp_max_cdeg", max(h))
            w("temp_sum_cdeg", sum(h)); w("temp_n", len(h)); w("temp_raw", 1700); w("vref_raw", 1200)

    def tick(self):
        return int(math.floor(self.device_ms())) % lb.U32

    def _usb(self):
        # Full-speed USB frames: mostly ~1 ms, sometimes a slow outlier.
        base = self.rng.uniform(0.4e6, 1.2e6)
        if self.rng.random() < 0.05:
            base += self.rng.uniform(2e6, 15e6)
        return int(base)

    def _firmware_poll(self):
        seq = self.ram[BLOCK_ADDR + 4 * lb.W["seq"]]
        if seq and not seq & 1:
            if self.ram[BLOCK_ADDR + 4 * lb.W["ack_seq"]] != seq:
                self.temp_hist = []                      # firmware restarts the stats on adoption
                for n in ("temp_min_cdeg", "temp_max_cdeg", "temp_sum_cdeg", "temp_n"):
                    self.ram[BLOCK_ADDR + 4 * lb.W[n]] = 0
            self.ram[BLOCK_ADDR + 4 * lb.W["ack_seq"]] = seq
        self._temp_update()

    def read32(self, addr):
        rtt = self._usb()
        split = self.rng.random()
        self.clock.t_ns += int(rtt * split)
        v = self.tick() if addr == TICK_ADDR else self.ram.get(addr, 0)
        self.clock.t_ns += rtt - int(rtt * split)
        return v

    def write32(self, addr, v):
        self.clock.t_ns += self._usb()
        self.ram[addr] = v & 0xFFFFFFFF

    def read_memory_block32(self, addr, n):
        self._firmware_poll()
        self.clock.t_ns += self._usb()
        return [self.ram.get(addr + 4 * i, 0) for i in range(n)]


def sync_args(**kw):
    a = argparse.Namespace(duration=600, interval=5.0, burst=8, bpm=120.0, period_ms=None, every=None,
                           epoch=0.0, refine=False, min_refine=600, horizon=6.0)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def resync_args(**kw):
    a = argparse.Namespace(duration=10.0, interval=1.0, burst=8, offset_samples=5, min_baseline=600,
                           warn_ppm=200, no_fallback=False, full_duration=600, bpm=None, period_ms=None,
                           every=None, epoch=None)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def expected_corr_ppb(ppm):
    """Correction that exactly cancels a clock running `ppm` fast: 1/(1+e) - 1."""
    return (1 / (1 + ppm * 1e-6) - 1) * 1e9


def true_offset_ms(dev, tgt, clock):
    blk = dev.read_block()
    return (lb.device_master_us(blk, tgt.tick()) - clock.wall_ns() / 1000) / 1000


class SyncTests(unittest.TestCase):
    def make(self, ppm, seed=1):
        clock = FakeClock()
        tgt = FakeTarget(clock, ppm, random.Random(seed))
        return clock, tgt, lb.Device(tgt, clock)

    def test_finds_block(self):
        _, _, dev = self.make(0)
        self.assertEqual(dev.addr, BLOCK_ADDR)
        self.assertEqual(dev.tick_addr, TICK_ADDR)

    def test_sync_recovers_rate_and_offset(self):
        for ppm in (-8000.0, -350.0, 0.0, 1234.5, 9500.0):
            clock, tgt, dev = self.make(ppm)
            res = lb.cmd_sync(dev, sync_args(), log=lambda *a: None)
            self.assertAlmostEqual(res["corr_ppb"], expected_corr_ppb(ppm), delta=1500, msg=f"ppm={ppm}")
            self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 1.5)
            clock.sleep(6 * 3600)                       # 6 h free-running, constant rate
            self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 40, msg=f"ppm={ppm}")

    def test_refine_uses_long_baseline(self):
        clock, tgt, dev = self.make(4321.0, seed=7)
        lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)   # deliberately short
        clock.sleep(3 * 3600)
        res = lb.cmd_sync(dev, sync_args(refine=True, duration=30), log=lambda *a: None)
        self.assertAlmostEqual(res["corr_ppb"], expected_corr_ppb(4321.0), delta=300)
        clock.sleep(6 * 3600)
        self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 8)

    def test_status_matches_truth(self):
        clock, tgt, dev = self.make(500.0)
        lb.cmd_sync(dev, sync_args(), log=lambda *a: None)
        tgt.ppm = 520.0                                 # device warms up: +20 ppm
        clock.sleep(4 * 3600)
        st = lb.cmd_status(dev, argparse.Namespace(samples=10), log=lambda *a: None)
        self.assertAlmostEqual(st["offset_ms"], true_offset_ms(dev, tgt, clock), delta=2)
        self.assertAlmostEqual(st["offset_ms"], 20e-6 * 4 * 3600 * 1000, delta=40)

    def test_rejects_wrong_tick_counter(self):
        clock, tgt, dev = self.make(0)
        tgt.ppm = 1e6                                   # "tick" runs at 2 kHz
        with self.assertRaises(lb.SyncError):
            lb.cmd_sync(dev, sync_args(duration=20), log=lambda *a: None)

    def test_refine_requires_previous_sync(self):
        _, _, dev = self.make(0)
        with self.assertRaises(lb.SyncError):
            lb.cmd_sync(dev, sync_args(refine=True), log=lambda *a: None)


class ResyncTests(unittest.TestCase):
    def make(self, ppm, seed=3, **kw):
        clock = FakeClock()
        tgt = FakeTarget(clock, ppm, random.Random(seed), **kw)
        return clock, tgt, lb.Device(tgt, clock)

    def quiet(self, dev, **kw):
        return lb.cmd_resync(dev, resync_args(**kw), log=lambda *a: None)

    def test_reads_uid_and_temperature(self):
        clock, tgt, dev = self.make(0, temp_fn=lambda t: 31.25)
        blk = dev.read_block()
        self.assertEqual(blk.uid, bytes(range(0x41, 0x51)).hex())
        self.assertEqual(blk.short_uid, "45-494a4b4c")
        self.assertIsNone(blk.temperature())            # no reading yet
        lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
        clock.sleep(120)
        t = dev.read_block().temperature()
        self.assertAlmostEqual(t["mean_c"], 31.25)
        self.assertAlmostEqual(t["min_c"], 31.25)
        self.assertGreater(t["n"], 5)

    def test_resync_is_quick_and_uses_previous_anchor(self):
        clock, tgt, dev = self.make(4321.0, seed=9)
        lb.cmd_sync(dev, sync_args(duration=60, every=3600.0, epoch=1_000_000.0), log=lambda *a: None)
        clock.sleep(3600)
        t0 = clock.t_ns
        rec = self.quiet(dev)
        self.assertLess((clock.t_ns - t0) / 1e9, 25)    # ~15 s of sampling, not 10 minutes
        self.assertEqual(rec["kind"], "resync")
        self.assertEqual(rec["rate_source"], "long")
        self.assertAlmostEqual(rec["raw_rate_ppm"], 4321.0, delta=4)
        self.assertAlmostEqual(rec["corr_ppb"], expected_corr_ppb(4321.0), delta=4000)
        self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 1.5)
        # the grid set by the first sync survives
        blk = dev.read_block()
        self.assertEqual((blk.period_us, blk.epoch_us), (3_600_000_000, 1_000_000_000_000))
        # and the record says whose it is
        self.assertEqual(rec["uid"], dev.read_block().uid)
        self.assertEqual(rec["temp"]["n"], 360)

    def test_repeated_hourly_visits_stay_in_sync(self):
        clock, tgt, dev = self.make(-2500.0, seed=11)
        lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
        for hour in range(6):
            tgt.set_ppm(-2500.0 + 30 * hour)            # warms up a little each hour
            clock.sleep(3600)
            self.quiet(dev)
            self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 1.5, msg=f"hour {hour}")
        clock.sleep(3600)
        self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 150)     # one more hour untouched

    def test_too_soon_keeps_previous_rate(self):
        clock, tgt, dev = self.make(800.0, seed=5)
        lb.cmd_sync(dev, sync_args(duration=120), log=lambda *a: None)
        corr = dev.read_block().corr_ppb
        clock.sleep(120)
        rec = self.quiet(dev)
        self.assertEqual(rec["rate_source"], "kept")
        self.assertIsNone(rec["raw_rate_ppm"])
        self.assertEqual(dev.read_block().corr_ppb, rec["corr_ppb"])
        self.assertAlmostEqual(rec["corr_ppb"], corr, delta=3000)      # re-anchored, rate unchanged-ish
        self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 1.5)

    def test_unsynced_device_falls_back_to_full_sync(self):
        clock, tgt, dev = self.make(1500.0, seed=2)
        t0 = clock.t_ns
        rec = self.quiet(dev, every=60.0, epoch=0.0, full_duration=120)
        self.assertEqual(rec["kind"], "sync")
        self.assertGreater((clock.t_ns - t0) / 1e9, 100)
        self.assertEqual(dev.read_block().period_us, 60_000_000)
        self.assertLess(abs(true_offset_ms(dev, tgt, clock)), 1.5)

    def test_no_fallback_refuses_unsynced(self):
        _, _, dev = self.make(0)
        with self.assertRaises(lb.SyncError):
            self.quiet(dev, no_fallback=True)

    def test_record_carries_battery_and_power_state(self):
        clock, tgt, dev = self.make(0, seed=6)
        lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
        for name, v in (("batt_mv", 3712), ("power_state", 1), ("wake_count", 3)):
            tgt.ram[BLOCK_ADDR + 4 * lb.W[name]] = v
        clock.sleep(1200)
        out = []
        rec = lb.cmd_resync(dev, resync_args(), log=out.append)
        self.assertEqual((rec["vcc_mv"], rec["low_battery"], rec["usb_input"], rec["wake_count"]),
                         (3712, True, False, 3))
        self.assertTrue(any("LOW-BATTERY" in line for line in out))
        self.assertTrue(any("3.712 V" in line for line in out))

    def test_new_grid_can_be_given(self):
        clock, tgt, dev = self.make(0, seed=4)
        lb.cmd_sync(dev, sync_args(duration=60, every=3600.0), log=lambda *a: None)
        clock.sleep(1800)
        self.quiet(dev, every=1800.0, epoch=5.0)
        blk = dev.read_block()
        self.assertEqual((blk.period_us, blk.epoch_us), (1_800_000_000, 5_000_000))


class VersionTests(unittest.TestCase):
    def target(self, **kw):
        clock = FakeClock()
        return clock, FakeTarget(clock, 0, random.Random(1), **kw)

    def test_units_report_firmware_and_format(self):
        clock, tgt = self.target(fw=(1, 2, 3), build=0xDEADBEEF, flags=1)
        dev = lb.Device(tgt, clock)
        h = dev.header
        self.assertEqual((h.major, h.minor, h.fw, h.build, h.dirty), (4, 0, (1, 2, 3), 0xDEADBEEF, True))
        self.assertEqual(dev.read_block().version_text,
                         "firmware 1.2.3 (build deadbeef+dirty), wire format 4.0")

    def test_unstamped_build_says_unknown(self):
        _, tgt = self.target(build=0)
        self.assertIn("build unknown", lb.describe_header(lb.find_blocks(tgt)[0]))

    def test_other_major_is_refused_with_a_useful_message(self):
        clock, tgt = self.target(fmt=(5, 0), fw=(0, 9, 0))
        with self.assertRaises(lb.SyncError) as cm:
            lb.Device(tgt, clock)
        msg = str(cm.exception)
        self.assertIn("firmware 0.9.0", msg)
        self.assertIn("wire format 5.0", msg)
        self.assertIn("speaks 4.0", msg)

    def test_newer_minor_than_known_is_read_as_its_known_prefix(self):
        clock, tgt = self.target(fmt=(4, 3), extra_words=5)          # a minor this script has never heard of
        dev = lb.Device(tgt, clock)
        self.assertEqual(len(dev.read_block().words), lb.BLOCK_WORDS)
        lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)

    def test_older_minor_is_read_with_its_own_layout_and_judged_per_command(self):
        """A unit on 4.0 talking to a script that knows 4.1 (which appends `extra`): commands that
        do not need `extra` still work; the one that does is refused, naming the missing field."""
        from lb_catalog import COMMANDS, FEATURES, FORMATS, MODELS, TRANSPORTS
        from lb_compat import Catalog, CommandNeeds, Feature, Fields, Formats, Variant
        specs = list(FORMATS.specs) + [lb_compat.FormatSpec(4, 1, adds=("extra",))]
        cat = Catalog(Formats(specs), FEATURES + [Feature("extra", (Variant("v1", Fields("extra")),), hardware=False)],
                      dict(COMMANDS, fancy=CommandNeeds(required=("extra",)),
                           sync=CommandNeeds(required=("clock_sync", "writable"), optional=("extra",))),
                      MODELS, TRANSPORTS)
        old = lb.CATALOG
        lb.CATALOG = cat
        try:
            clock, tgt = self.target(fmt=(4, 0))
            dev = lb.Device(tgt, clock)
            self.assertEqual(len(dev.read_block().words), lb.BLOCK_WORDS)         # its own, shorter layout
            out = []
            lb.cmd_sync(dev, sync_args(duration=60), log=out.append)               # optional `extra` missing: runs
            self.assertTrue(any("cannot report extra" in line for line in out), out)
            with self.assertRaises(lb.SyncError) as cm:
                dev.require("fancy")
            self.assertIn("wire format 4.0 has no extra", str(cm.exception))
            self.assertIn("firmware 0.4.0", str(cm.exception))
        finally:
            lb.CATALOG = old

    def test_read_only_connection_can_report_but_not_sync(self):
        clock, tgt = self.target()
        dev = lb.Device(tgt, clock)
        u = dev.unit                                     # the same unit reached over a link that cannot write
        dev.unit = lb_compat.Unit(u.major, u.minor, u.fw, u.layout, u.model, "swd", frozenset({"read"}))
        dev.require("status")
        with self.assertRaises(lb.SyncError) as cm:
            dev.require("sync")
        self.assertIn("cannot write", str(cm.exception))

    def test_model_word_is_reported_and_logged(self):
        clock, tgt = self.target()
        dev = lb.Device(tgt, clock)
        self.assertEqual(dev.unit.model.name, "py32-bug")
        self.assertEqual(dev.read_block().model_id, 0)
        rec = lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
        self.assertEqual(rec["model"], "py32-bug")

    def test_unknown_model_is_refused_with_its_id(self):
        clock, tgt = self.target()
        tgt.ram[BLOCK_ADDR + 4 * lb.W["model_id"]] = 9
        dev = lb.Device(tgt, clock)                      # still readable: `info` and friends work
        with self.assertRaises(lb.SyncError) as cm:
            dev.require("sync")
        self.assertIn("unknown(id 9)", str(cm.exception))

    def test_info_lists_features_and_commands(self):
        _, tgt = self.target()
        out = []
        lb.cmd_info(tgt, None, log=out.append)
        text = "\n".join(out)
        for word in ("temperature", "clock_sync", "resync", "model py32-bug"):
            self.assertIn(word, text)

    def test_truncated_block_is_refused(self):
        clock, tgt = self.target()
        tgt.ram[BLOCK_ADDR + 4 * lb.W["block_words"]] = lb.BLOCK_WORDS - 3
        with self.assertRaises(lb.SyncError) as cm:
            lb.Device(tgt, clock)
        self.assertIn("words", str(cm.exception))

    def test_legacy_block_is_recognised_not_mistaken_for_no_block(self):
        clock, tgt = self.target()
        # Formats 1-3: [2] = small version number, [3] = &uwTick.
        tgt.ram[BLOCK_ADDR + 8] = 3
        tgt.ram[BLOCK_ADDR + 12] = TICK_ADDR
        (h,) = lb.find_blocks(tgt)
        self.assertTrue(h.legacy)
        self.assertEqual(h.major, 3)
        self.assertIn("older than version reporting", lb.describe_header(h))
        with self.assertRaises(lb.SyncError) as cm:
            lb.Device(tgt, clock)
        self.assertIn("wire format 3", str(cm.exception))
        self.assertNotIn("no Lightning Bugs sync block", str(cm.exception))

    def test_info_reports_any_format_without_raising(self):
        for fmt, expect in (((4, 0), "compatible"), ((9, 1), "NOT compatible")):
            _, tgt = self.target(fmt=fmt)
            out = []
            lb.cmd_info(tgt, None, log=out.append)
            self.assertTrue(any(expect in line for line in out), msg=out)
            self.assertTrue(any("firmware 0.4.0" in line for line in out))

    def test_info_without_a_block(self):
        class Empty:
            def read_memory_block32(self, a, n):
                return [0] * n
        with self.assertRaises(lb.SyncError):
            lb.cmd_info(Empty(), None)

    def test_visit_log_and_report_carry_the_version(self):
        clock = FakeClock()
        tgt = FakeTarget(clock, 100.0, random.Random(2), fw=(0, 4, 1), build=0xABC12345)
        dev = lb.Device(tgt, clock)
        rec = lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
        self.assertEqual((rec["fw"], rec["fw_build"], rec["fw_dirty"], rec["format"]),
                         ("0.4.1", "abc12345", False, "4.0"))
        rep = lb.drift_report([rec, dict(rec, fw="0.3.0", fw_build="")])
        out = []
        lb.print_report(rep, out.append)
        self.assertTrue(any("firmware in this log" in line and "0.4.1" in line for line in out))
        self.assertTrue(any("more than one build" in line for line in out))


class GridTests(unittest.TestCase):
    def test_every_sets_the_period(self):
        epoch, period = lb.grid_from_args(sync_args(every=3600.0, epoch=7.0))
        self.assertEqual((epoch, period), (7_000_000, 3_600_000_000))

    def test_period_must_fit_32_bits(self):
        with self.assertRaises(lb.SyncError):
            lb.grid_from_args(sync_args(every=4300.0))


class LogAndReportTests(unittest.TestCase):
    def test_log_roundtrip_and_bad_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "log.jsonl"
            lb.append_log(path, {"a": 1})
            lb.append_log(path, {"b": [2, 3]})
            self.assertEqual(lb.load_log(path), [{"a": 1}, {"b": [2, 3]}])
            path.write_text('{"a": 1}\nnot json\n')
            with self.assertRaises(lb.SyncError):
                lb.load_log(path)

    @staticmethod
    def visit(uid, rate, temp, elapsed=3600.0, drift=None, source="long"):
        r = {"kind": "resync", "uid": uid, "short_uid": uid[:4], "rate_source": source,
             "raw_rate_ppm": rate, "elapsed_s": elapsed, "temp": {"mean_c": temp, "n": 360}}
        if drift is not None:
            r["drift_ms"] = drift
        return r

    def test_report_recovers_temperature_coefficient_and_unit_spread(self):
        k = -3.0                                          # ppm per degC
        recs = []
        for uid, base in (("aa" * 16, 1000.0), ("bb" * 16, 1400.0), ("cc" * 16, 600.0)):
            for temp in (22.0, 25.0, 28.0, 31.0, 34.0):
                recs.append(self.visit(uid, base + k * (temp - 25.0), temp, drift=5.0))
        rep = lb.drift_report(recs)
        p = rep["pooled"]
        self.assertEqual((p["visits"], p["devices"]), (15, 3))
        self.assertAlmostEqual(p["ppm_per_degc_within"], k, places=6)
        self.assertAlmostEqual(rep["devices"]["aa" * 16]["ppm_per_degc"], k, places=6)
        # unit-to-unit offsets are not mistaken for a temperature effect in the within-device slope
        self.assertAlmostEqual(p["between_device_sd_ppm"], 400.0, places=6)
        self.assertAlmostEqual(rep["devices"]["bb" * 16]["residual_ms_per_h_mean"], 5.0)
        out = []
        lb.print_report(rep, out.append)
        self.assertTrue(any("ppm/°C" in line for line in out))

    def test_battery_trend_and_projection(self):
        def rec(day, mv, usb=False):
            return {"uid": "aa" * 16, "short_uid": "aa-bb", "wall_s": 1_000_000 + day * 86400,
                    "vcc_mv": mv, "usb_input": usb}
        recs = [rec(0, 4000), rec(1, 3980), rec(2, 3960), rec(3, 3940), rec(2.5, 4150, usb=True)]
        bat = lb.battery_report(recs)["aa" * 16]
        self.assertEqual(bat["visits"], 4)                  # the visit on a charger is not a discharge point
        self.assertAlmostEqual(bat["mv_per_day"], -20.0, places=6)
        self.assertAlmostEqual(bat["days_to_sleep"], (3940 - 3600) / 20, places=6)
        out = []
        lb.print_report(lb.drift_report(recs), out.append)
        self.assertTrue(any("mV/day" in line and "aa-bb" in line for line in out))

    def test_battery_needs_a_trend(self):
        recs = [{"uid": "aa" * 16, "wall_s": 1000 + i, "vcc_mv": 3900} for i in range(3)]   # all within a minute
        self.assertNotIn("days_to_sleep", lb.battery_report(recs)["aa" * 16])

    def test_report_skips_unusable_visits(self):
        recs = [self.visit("aa" * 16, 10.0, 25.0, source="short"),
                self.visit("aa" * 16, None, 25.0),
                {"kind": "resync", "uid": "aa" * 16, "rate_source": "long", "raw_rate_ppm": 5.0,
                 "elapsed_s": 3600, "temp": None},
                self.visit("aa" * 16, 7.0, 26.0)]
        rep = lb.drift_report(recs)
        self.assertEqual(rep["pooled"]["visits"], 1)
        self.assertEqual(rep["skipped"], 3)
        out = []
        lb.print_report(lb.drift_report([]), out.append)
        self.assertIn("No usable visits", out[0])

    def test_end_to_end_hourly_visits_measure_temperature_effect(self):
        """Simulated devices whose clock depends on temperature; resync visits + report find it."""
        k = 8.0                                           # ppm per degC
        recs = []
        for n, (base, uid) in enumerate(((2000.0, bytes([1] * 16)), (-1200.0, bytes([2] * 16)))):
            clock = FakeClock()
            tgt = FakeTarget(clock, base, random.Random(40 + n), uid=uid, temp_fn=lambda t: 25.0)
            dev = lb.Device(tgt, clock)
            lb.cmd_sync(dev, sync_args(duration=60), log=lambda *a: None)
            for hour, temp in enumerate((24, 28, 33, 29, 26, 31, 35, 27)):
                tgt.set_ppm(base + k * (temp - 25))
                tgt.temp_fn = lambda t, T=temp: float(T)
                clock.sleep(3600)
                recs.append(lb.cmd_resync(dev, resync_args(), log=lambda *a: None))
        rep = lb.drift_report(recs)
        self.assertEqual(rep["pooled"]["visits"], 16)
        # each hour's rate is the clock's real rate over that hour
        self.assertAlmostEqual(rep["pooled"]["ppm_per_degc_within"], k, delta=1.0)
        self.assertAlmostEqual(rep["pooled"]["between_device_sd_ppm"], abs(2000 + 1200) / math.sqrt(2), delta=120)


class FormulaTests(unittest.TestCase):
    def test_c_div_truncates(self):
        self.assertEqual(lb.c_div(7, 2), 3)
        self.assertEqual(lb.c_div(-7, 2), -3)
        self.assertEqual(lb.c_div(7, -2), -3)

    def test_firmware_formula_fits_int64(self):
        # Worst case the device can see: L = ±2^31 ms, corr = ±5 %.
        for L in (2**31 - 1, -(2**31)):
            for corr in (lb.MAX_CORR_PPB, -lb.MAX_CORR_PPB):
                self.assertLess(abs(L * corr), 2**63)
                self.assertLess(abs(L * 1000 + lb.c_div(L * corr, 10**6)) + 2**62, 2**63)


if __name__ == "__main__":
    unittest.main()
