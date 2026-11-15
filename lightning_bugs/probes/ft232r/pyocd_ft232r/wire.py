"""Pin map and bit-stream encoding for SWD over synchronous bit-bang.

Electrical model (the FT232R has no MPSSE, so SWDIO cannot change direction mid-frame):

    SWDIO_OUT pin --[~470 ohm]--+-- SWDIO (target)
    SWDIO_IN  pin --------------+
    SWCLK     pin ------------------- SWCLK (target)

The host always drives SWDIO_OUT through the resistor. To *read*, it drives 1; the target pulls
the line low through its (much stronger) driver when it sends a 0, and SWDIO_IN reads the line.

Bit-bang timing: one SWD clock cycle is two bytes, [SWCLK low][SWCLK high]. The target samples
SWDIO on the rising edge and changes its own output after the rising edge (ARM ADI, same as CMSIS-DAP's
SW_READ_BIT), so the host samples SWDIO from the *low* byte of a read cycle.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pins:
    """FT232R bit-bang pin numbers (D0..D7 = TXD, RXD, RTS#, CTS#, DTR#, DSR#, DCD#, RI#)."""
    swclk: int = 0          # TXD
    swdio_out: int = 1      # RXD (all eight pins can be outputs in bit-bang mode)
    swdio_in: int = 3       # CTS#
    nreset: int | None = None   # optional; pushed low to assert reset, high to release

    def __post_init__(self):
        used = [self.swclk, self.swdio_out, self.swdio_in] + ([self.nreset] if self.nreset is not None else [])
        if any(not isinstance(p, int) or not 0 <= p <= 7 for p in used):
            raise ValueError(f"pins must be integers 0..7, got {used}")
        if len(set(used)) != len(used):
            raise ValueError(f"pins must all be different, got {used}")

    @property
    def direction_mask(self) -> int:
        """Bit-bang direction byte: 1 = output."""
        mask = (1 << self.swclk) | (1 << self.swdio_out)
        if self.nreset is not None:
            mask |= 1 << self.nreset
        return mask

    @classmethod
    def parse(cls, text: str) -> "Pins":
        """Parse 'swclk=0,swdio_out=1,swdio_in=3[,nreset=2]' (any subset; others keep defaults)."""
        kw = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            key, sep, val = part.partition("=")
            key = key.strip()
            if not sep or key not in ("swclk", "swdio_out", "swdio_in", "nreset"):
                raise ValueError(f"bad pin spec {part!r}; use swclk=N,swdio_out=N,swdio_in=N[,nreset=N]")
            kw[key] = int(val, 0)
        return cls(**kw)


class Batch:
    """Builds the byte stream for a sequence of SWD bits and decodes the returned samples."""

    def __init__(self, pins: Pins, nreset_level: int = 1):
        self.pins = pins
        self._rst = (nreset_level & 1) << pins.nreset if pins.nreset is not None else 0
        self.out = bytearray()
        self._reads: list[list[int]] = []        # per read: sample index of each bit

    def _byte(self, clk: int, dio: int) -> int:
        return (clk << self.pins.swclk) | (dio << self.pins.swdio_out) | self._rst

    def write_bits(self, value: int, n: int) -> None:
        """Host drives `n` bits of `value`, LSB first."""
        for i in range(n):
            dio = (value >> i) & 1
            self.out.append(self._byte(0, dio))
            self.out.append(self._byte(1, dio))

    def clock(self, n: int = 1) -> None:
        """`n` clock cycles with SWDIO released (turnaround); nothing is sampled."""
        for _ in range(n):
            self.out.append(self._byte(0, 1))
            self.out.append(self._byte(1, 1))

    def read_bits(self, n: int) -> int:
        """Clock `n` cycles with SWDIO released and sample each; returns a handle for decode()."""
        idx = []
        for _ in range(n):
            idx.append(len(self.out))            # the low byte
            self.out.append(self._byte(0, 1))
            self.out.append(self._byte(1, 1))
        self._reads.append(idx)
        return len(self._reads) - 1

    def decode(self, samples: bytes) -> list[int]:
        """Return one integer per read_bits() call (LSB = first bit on the wire)."""
        if len(samples) != len(self.out):
            raise ValueError(f"expected {len(self.out)} samples, got {len(samples)}")
        sh = self.pins.swdio_in
        return [sum(((samples[i] >> sh) & 1) << k for k, i in enumerate(idx)) for idx in self._reads]
