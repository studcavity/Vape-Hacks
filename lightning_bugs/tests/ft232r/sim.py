"""A pin-level simulation of an FT232R wired to an SWD target, for testing the FT232R probe plugin
with no hardware.

SimGpio    stands in for pyftdi's GpioSyncController: bytes in, one sample byte out per byte, with a
           configurable sample lag and an optional missing SWDIO loopback (bridge).
SimTarget  a Cortex-M0-like SW-DP + one MEM-AP over RAM, driven bit by bit from SWCLK/SWDIO.
           It follows the same convention as the plugin: the target samples SWDIO on the rising edge
           and changes its own output after it. Faults can be injected (WAIT, FAULT, bad parity).
"""
from __future__ import annotations

RAM_BASE = 0x20000000
ACK_OK, ACK_WAIT, ACK_FAULT = 0b001, 0b010, 0b100


def parity(v):
    return bin(v & 0xFFFFFFFF).count("1") & 1


class SimTarget:
    DPIDR = 0x0BC11477
    AP_IDR = 0x04770021

    def __init__(self, ram_words=2048):
        self.ram = [0] * ram_words
        self.read_hooks = {}                 # word address -> callable returning the value
        self.writes = []                     # (address, value) of every memory write
        self.log = []                        # executed (apndp, rnw, addr, value) transactions
        self.wait_count = 0                  # answer the next N requests with WAIT
        self.fault_count = 0                 # answer the next N requests with FAULT
        self.flip_read_parity = 0            # corrupt the parity bit of the next N reads
        self.swd_enabled = False
        self.line_resets = 0
        self.protocol_errors = 0
        self._reset_dp()
        self.phase, self.ones, self.hist, self.prev_clk = "idle", 0, 0, 0
        self.drive = None
        self.bits = []

    # ── DP/AP register model ────────────────────────────────────────────────
    def _reset_dp(self):
        self.select = self.ctrl = self.rdbuff = 0
        self.csw, self.tar = 0x23000042, 0

    def _mem_read(self, addr):
        if addr in self.read_hooks:
            return self.read_hooks[addr]() & 0xFFFFFFFF
        i = (addr - RAM_BASE) // 4
        return self.ram[i] if 0 <= i < len(self.ram) else 0

    def _mem_write(self, addr, v):
        self.writes.append((addr, v))
        i = (addr - RAM_BASE) // 4
        if 0 <= i < len(self.ram):
            self.ram[i] = v

    def _ap_read_reg(self, reg):
        if reg == 0x00: return self.csw
        if reg == 0x04: return self.tar
        if reg == 0x0C:
            v = self._mem_read(self.tar)
            if (self.csw >> 4) & 3 == 1:
                self.tar += 4
            return v
        if reg == 0xF4: return 0
        if reg == 0xF8: return 0xE00FF003
        if reg == 0xFC: return self.AP_IDR
        return 0

    def _ap_write_reg(self, reg, v):
        if reg == 0x00: self.csw = v
        elif reg == 0x04: self.tar = v
        elif reg == 0x0C:
            self._mem_write(self.tar, v)
            if (self.csw >> 4) & 3 == 1:
                self.tar += 4

    def _execute(self, apndp, rnw, a, value=0):
        self.log.append((apndp, rnw, a, value))
        if not apndp:
            if rnw:
                if a == 0x0: return self.DPIDR
                if a == 0x4:
                    ack = (0x80000000 if self.ctrl & 0x40000000 else 0) | (0x20000000 if self.ctrl & 0x10000000 else 0)
                    return self.ctrl | ack
                if a == 0x8: return self.select
                return self.rdbuff
            if a == 0x4: self.ctrl = value
            elif a == 0x8: self.select = value
            return 0
        reg = ((self.select >> 4) & 0xF) << 4 | a
        if rnw:                              # posted: return the previous result, start the new read
            ret, self.rdbuff = self.rdbuff, self._ap_read_reg(reg)
            return ret
        self._ap_write_reg(reg, value)
        return 0

    # ── bit-level protocol ──────────────────────────────────────────────────
    def step(self, clk, dio):
        """Apply one bit-bang byte (SWCLK=clk, host SWDIO_OUT level=dio); return the SWDIO line level."""
        if clk and not self.prev_clk:
            self._rising(dio)
        self.prev_clk = clk
        return dio if self.drive is None else self.drive

    def _rising(self, dio):
        ph = self.phase
        if ph == "idle":
            self._idle_bit(dio)
        elif ph == "header":
            self.bits.append(dio)
            if len(self.bits) == 8:
                self._header_done()
        elif ph == "turn1":
            self.phase, self.i = "ack", 0
            self.drive = self.ack & 1
        elif ph == "ack":
            self.i += 1
            if self.i < 3:
                self.drive = (self.ack >> self.i) & 1
            else:
                self._ack_done()
        elif ph == "rdata":
            self.i += 1
            if self.i < 33:
                self.drive = self.rbits[self.i]
            else:
                self.drive, self.phase = None, "trn_r"
        elif ph == "trn_r":
            self.phase, self.ones = "idle", 0
        elif ph == "turn2":
            self.phase, self.bits = "wdata", []
        elif ph == "wdata":
            self.bits.append(dio)
            if len(self.bits) == 33:
                v = sum(b << k for k, b in enumerate(self.bits[:32]))
                if self.bits[32] == parity(v):
                    self._execute(*self.req, v)
                else:
                    self.protocol_errors += 1
                self.phase, self.ones = "idle", 0

    def _idle_bit(self, dio):
        prev_ones = self.ones
        if dio:
            self.ones += 1
        else:
            if self.ones >= 50:
                self.line_resets += 1
                self._reset_dp()
            self.ones = 0
        self.hist = ((self.hist >> 1) | (dio << 15)) & 0xFFFF
        if self.hist == 0xE79E:
            self.swd_enabled = True
        if dio and prev_ones == 0 and self.swd_enabled:
            self.phase, self.bits = "header", [1]

    def _header_done(self):
        b = self.bits
        ok = b[0] == 1 and b[6] == 0 and b[7] == 1 and (b[1] + b[2] + b[3] + b[4]) & 1 == b[5]
        if not ok:
            self.protocol_errors += 1
            self.phase, self.ones = "idle", 0
            while b and b[-1 - (self.ones)] == 1 and self.ones < len(b) - 1:
                self.ones += 1
            return
        apndp, rnw, a = b[1], b[2], (b[3] << 2) | (b[4] << 3)
        self.req = (apndp, rnw, a)
        if self.wait_count:
            self.wait_count -= 1
            self.ack = ACK_WAIT
        elif self.fault_count:
            self.fault_count -= 1
            self.ack = ACK_FAULT
        else:
            self.ack = ACK_OK
            if rnw:
                v = self._execute(apndp, rnw, a)
                pbit = parity(v) ^ (1 if self.flip_read_parity else 0)
                self.flip_read_parity = max(0, self.flip_read_parity - 1)
                self.rbits = [(v >> k) & 1 for k in range(32)] + [pbit]
        self.phase = "turn1"

    def _ack_done(self):
        apndp, rnw, a = self.req
        if self.ack == ACK_OK and rnw:
            self.phase, self.i, self.drive = "rdata", 0, self.rbits[0]
        elif self.ack == ACK_OK:
            self.phase, self.drive = "turn2", None
        else:                                # WAIT/FAULT: no data phase; whatever the host clocks is seen as idle
            self.phase, self.drive, self.ones = "idle", None, 1


class SimGpio:
    """Duck-types pyftdi.gpio.GpioSyncController for FtdiTransport."""

    def __init__(self, target=None, lag=1, bridge=True):
        self.target = target if target is not None else SimTarget()
        self.lag = lag
        self.bridge = bridge                 # False: SWDIO_IN is not wired to SWDIO
        self.exchanges = 0
        self.sent = bytearray()
        self.frequency = 0.0
        self.latency = None
        self.closed = False
        self.ftdi = self

    # pyftdi surface used by FtdiTransport
    def configure(self, url, direction, frequency, initial):
        self.url, self.direction, self.frequency = url, direction, float(frequency)
        self._delayed = [self._sample(initial)] * self.lag

    def set_frequency(self, hz):
        self.frequency = float(hz)

    def set_latency_timer(self, ms):
        self.latency = ms

    def close(self, freeze=False):
        self.closed = True

    def exchange(self, out):
        self.exchanges += 1
        self.sent += out
        res = bytearray()
        for byte in out:
            self._delayed.append(self._sample(byte))
            res.append(self._delayed.pop(0))
        return bytes(res)

    # ── pin model ───────────────────────────────────────────────────────────
    _pins = None

    def _sample(self, byte):
        p = self._pins
        clk, dio = (byte >> p.swclk) & 1, (byte >> p.swdio_out) & 1
        level = self.target.step(clk, dio)
        return (byte & 0xFF & ~(1 << p.swdio_in)) | ((level if self.bridge else 0) << p.swdio_in)


def make_gpio_factory(gpio, pins):
    """Factory for FtdiTransport(gpio_factory=...) that gives it `gpio` (with the pin map set)."""
    gpio._pins = pins
    return lambda: gpio
