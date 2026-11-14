"""
Simulated-device tests for lb_sync.py. No hardware or pyocd needed:
    python3 -m unittest test_lb_sync.py
"""
import argparse
import math
import random
import unittest

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
    def __init__(self, clock, ppm, rng, boot_tick=4_294_000_000):
        self.clock, self.ppm, self.rng = clock, ppm, rng
        self.boot_ns = clock.t_ns
        self.boot_tick = boot_tick                      # start near wrap to test unwrapping
        self.ram = {}
        init = [lb.MAGIC0, lb.MAGIC1, lb.VERSION, TICK_ADDR] + [0] * (lb.BLOCK_WORDS - 4)
        init[lb.W["period_us"]] = 500_000
        for i, v in enumerate(init):
            self.ram[BLOCK_ADDR + 4 * i] = v

    def device_ms(self):
        t = (self.clock.t_ns - self.boot_ns) / 1e9
        return self.boot_tick + t * 1000 * (1 + self.ppm * 1e-6)

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
            self.ram[BLOCK_ADDR + 4 * lb.W["ack_seq"]] = seq

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
    a = argparse.Namespace(duration=600, interval=5.0, burst=8, bpm=120.0, period_ms=None,
                           epoch=0.0, refine=False, min_refine=600, horizon=6.0)
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
