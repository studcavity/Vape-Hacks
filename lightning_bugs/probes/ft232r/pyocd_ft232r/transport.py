"""The FTDI side: pyftdi's synchronous bit-bang controller, plus a loopback self-test.

Synchronous bit-bang returns one input sample per output byte, but how the sample lines up with the
byte just written depends on the chip's FIFO timing and is not documented precisely enough to rely
on. So `calibrate()` measures it: with SWCLK held low (the target sees no clock), a known pattern is
sent on SWDIO_OUT and read back on SWDIO_IN through the wiring, which also proves the
SWDIO_OUT --[R]-- SWDIO <-- SWDIO_IN bridge is in place. The measured lag is then removed from every
exchange, so callers always get "the pin state after this byte was applied".
"""
from __future__ import annotations

import logging

from .wire import Pins

LOG = logging.getLogger(__name__)

VID, PID = 0x0403, 0x6001           # FT232R
MIN_SWD_HZ, MAX_SWD_HZ = 10_000, 500_000     # MAX is a guess until measured on hardware
MAX_LAG = 3                          # sample lag, in bytes, that calibrate() will search

# 48 fixed pseudo-random bits: alignment is unambiguous for lags 0..MAX_LAG.
_PATTERN_BITS = [(0xB5E39A4D61C7 >> i) & 1 for i in range(48)]


class CalibrationError(Exception):
    pass


def calibrate(raw_exchange, pins: Pins, idle_level: int = 0) -> int:
    """Return the sample lag (0..MAX_LAG) of `raw_exchange(bytes) -> bytes`, or raise CalibrationError.

    `idle_level` is OR-ed into every byte (e.g. the nRESET pin held high).
    """
    out = bytes(idle_level | (b << pins.swdio_out) for b in _PATTERN_BITS)
    raw = raw_exchange(out)
    got = [(s >> pins.swdio_in) & 1 for s in raw]
    for lag in range(MAX_LAG + 1):
        if got[lag:] == _PATTERN_BITS[:len(got) - lag]:
            return lag
    raise CalibrationError(
        "SWDIO loopback test failed: SWDIO_IN did not follow SWDIO_OUT. Check the wiring: "
        "SWDIO_OUT pin -> ~470 ohm resistor -> SWDIO, and SWDIO_IN pin straight to SWDIO "
        f"(pins: swclk={pins.swclk} swdio_out={pins.swdio_out} swdio_in={pins.swdio_in}); "
        "also check the target is not holding SWDIO.")


class FtdiTransport:
    """exchange(bytes) -> bytes over an FT232R in synchronous bit-bang mode."""

    def __init__(self, url: str, pins: Pins, latency_ms: int = 1, gpio_factory=None):
        self.url, self.pins, self.latency_ms = url, pins, latency_ms
        self._gpio_factory = gpio_factory         # tests inject a simulated pyftdi controller
        self.lag = 0
        self.sample_hz = 0.0
        self._gpio = None

    def open(self, swd_hz: float, idle_level: int = 0) -> None:
        if self._gpio_factory is None:
            from pyftdi.gpio import GpioSyncController as factory
        else:
            factory = self._gpio_factory
        gpio = factory()
        # initial: SWCLK low, SWDIO_OUT high (line idle)
        gpio.configure(self.url, direction=self.pins.direction_mask,
                       frequency=self._sample_hz(swd_hz),
                       initial=(1 << self.pins.swdio_out) | idle_level)
        self._gpio = gpio
        try:
            gpio.ftdi.set_latency_timer(self.latency_ms)
        except Exception as e:                       # not fatal: only slower
            LOG.warning("could not set FTDI latency timer: %s", e)
        self.sample_hz = gpio.frequency
        self.lag = 0
        self.lag = calibrate(self.exchange, self.pins, idle_level)
        LOG.debug("FT232R bit-bang: %.0f samples/s, sample lag %d", self.sample_hz, self.lag)

    @staticmethod
    def _sample_hz(swd_hz: float) -> float:
        swd_hz = max(MIN_SWD_HZ, min(float(swd_hz), MAX_SWD_HZ))
        return 2 * swd_hz                            # two bytes per SWD clock cycle

    def set_swd_clock(self, swd_hz: float) -> None:
        self._gpio.set_frequency(self._sample_hz(swd_hz))
        self.sample_hz = self._gpio.frequency

    def exchange(self, out: bytes) -> bytes:
        if self.lag:
            raw = self._gpio.exchange(bytes(out) + bytes(out[-1:]) * self.lag)
            return bytes(raw[self.lag:])
        return bytes(self._gpio.exchange(bytes(out)))

    def close(self) -> None:
        if self._gpio is not None:
            try:
                self._gpio.close(freeze=True)        # leave the pins as they are (SWCLK low, SWDIO high)
            finally:
                self._gpio = None
