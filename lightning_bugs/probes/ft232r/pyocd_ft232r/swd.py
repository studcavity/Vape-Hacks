"""SWD transactions over a bit-bang transport.

`SwdLink` queues register transactions and runs them as one blind exchange (header, ACK and data
phases back to back), like the Picoprobe's bulk path. The ACKs are checked afterwards; on a WAIT the
failed tail of the batch is retried, on anything else the batch is abandoned and the line is flushed
with idle cycles so a half-clocked frame cannot be mistaken for a request.

The transport is anything with `exchange(bytes) -> bytes` returning one sample per output byte.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .wire import Batch, Pins

LOG = logging.getLogger(__name__)

ACK_OK, ACK_WAIT, ACK_FAULT = 0b001, 0b010, 0b100
IDLE_CYCLES = 3             # SWDIO low after every transaction
RECOVERY_CYCLES = 16        # SWDIO low after a failed batch: flushes any partial request
MAX_BATCH = 48              # transactions per exchange (about 2.5 KB of bit-bang bytes each way)
WAIT_RETRIES = 32
RDBUFF = 0xC


def header(apndp: int, rnw: int, addr: int) -> int:
    """The 8-bit SWD request, LSB first: start, APnDP, RnW, A2, A3, parity, stop(0), park(1)."""
    a2, a3 = (addr >> 2) & 1, (addr >> 3) & 1
    parity = (apndp + rnw + a2 + a3) & 1
    return 1 | apndp << 1 | rnw << 2 | a2 << 3 | a3 << 4 | parity << 5 | 0 << 6 | 1 << 7


def parity32(value: int) -> int:
    return bin(value & 0xFFFFFFFF).count("1") & 1


@dataclass
class Txn:
    apndp: int
    rnw: int
    addr: int
    value: int = 0                    # write data
    result: int | None = None         # read data
    error: Exception | None = None
    done: bool = False
    _handles: tuple = field(default=(), repr=False)


def _error_for(why) -> Exception:
    # Imported here: pyocd.core imports the probe plugins, so a module-level import would be circular.
    from pyocd.core import exceptions
    if why == "parity":
        return exceptions.ProbeError("FT232R: bad parity in SWD read")
    if why == ACK_WAIT:
        return exceptions.TransferTimeoutError("FT232R: SWD ACK WAIT (retries exhausted)")
    if why == ACK_FAULT:
        return exceptions.TransferFaultError("FT232R: SWD ACK FAULT")
    if why == "reordered":
        return exceptions.TransferError(
            "FT232R: SWD WAIT in the middle of a pipelined batch after which later transactions "
            "were accepted; cannot replay safely. Retry the operation, or use ft232r.safe=1.")
    return exceptions.TransferError(
        f"FT232R: SWD protocol error (ACK=0b{why:03b}); is the target connected and in SWD mode?")


class SwdLink:
    def __init__(self, transport, pins: Pins, nreset_level: int = 1, safe: bool = False):
        self.transport = transport
        self.pins = pins
        self.nreset_level = nreset_level
        self.safe = safe                 # one transaction per exchange: slow, but frames never run blind past an error
        self.queue: list[Txn] = []

    # ── raw sequences ────────────────────────────────────────────────────────
    def _run(self, batch: Batch) -> list[int]:
        return batch.decode(self.transport.exchange(bytes(batch.out)))

    def _batch(self) -> Batch:
        return Batch(self.pins, self.nreset_level)

    def idle_line(self) -> None:
        """Park the lines (SWCLK low, SWDIO high) and apply the current nRESET level."""
        b = self._batch()
        b.out.append(b._byte(0, 1))
        self._run(b)

    def swj_sequence(self, length: int, bits: int) -> None:
        self.flush()
        while length > 0:
            n = min(length, 64)
            b = self._batch()
            b.write_bits(bits & ((1 << n) - 1), n)
            self._run(b)
            bits >>= n
            length -= n

    def swd_sequence(self, sequences) -> list[bytes]:
        """Each item is (cycles,) to read or (cycles, value) to write; returns the bytes read."""
        self.flush()
        b = self._batch()
        order = []
        for seq in sequences:
            if len(seq) == 1:
                order.append((b.read_bits(seq[0]), (seq[0] + 7) // 8))
            else:
                b.write_bits(seq[1], seq[0])
        vals = self._run(b)
        return [vals[h].to_bytes(n, "little") for h, n in order]

    # ── transactions ─────────────────────────────────────────────────────────
    def enqueue(self, apndp: int, rnw: int, addr: int, value: int = 0) -> Txn:
        t = Txn(apndp, rnw, addr & 0xC, value & 0xFFFFFFFF)
        self.queue.append(t)
        if len(self.queue) >= MAX_BATCH or self.safe:
            self.flush()
        return t

    def _frame(self, b: Batch, t: Txn) -> None:
        b.write_bits(header(t.apndp, t.rnw, t.addr), 8)
        b.clock(1)                                           # turnaround, target takes SWDIO
        ack = b.read_bits(3)
        if t.rnw:
            data = b.read_bits(32)
            par = b.read_bits(1)
            b.clock(1)                                       # turnaround, host takes SWDIO back
            t._handles = (ack, data, par)
        else:
            b.clock(1)                                       # turnaround
            b.write_bits(t.value | parity32(t.value) << 32, 33)
            t._handles = (ack,)
        b.write_bits(0, IDLE_CYCLES)

    def flush(self) -> None:
        """Run everything queued. Raises the first transaction error (earlier results stay valid)."""
        pending, self.queue = self.queue, []
        attempts = 0
        while pending:
            batch = self._batch()
            for t in pending:
                self._frame(batch, t)
            vals = self._run(batch)
            failed = None
            for i, t in enumerate(pending):
                ack = vals[t._handles[0]]
                if ack != ACK_OK:
                    failed = (i, ack)
                    break
                if t.rnw:
                    data, par = vals[t._handles[1]], vals[t._handles[2]]
                    if parity32(data) != par:
                        failed = (i, "parity")
                        break
                    t.result = data
                t.done = True
            if failed is None:
                return
            i, why = failed
            self._recover()
            rest = pending[i:]
            # Frames are separated by idle cycles, so after a WAIT the *later* frames of the batch may
            # still have been accepted. Replaying from the WAIT would then run transactions twice and
            # out of order (fatal for auto-incrementing writes), so only replay when none of them ran.
            later_ran = any(vals[t._handles[0]] == ACK_OK for t in pending[i + 1:])
            if why == ACK_WAIT and not later_ran and attempts < WAIT_RETRIES:
                attempts += 1
                pending = rest
                continue
            if why == ACK_WAIT and later_ran:
                err = _error_for("reordered")
            else:
                err = _error_for(why)
            for t in rest:
                t.error = err
            raise err

    def _recover(self) -> None:
        b = self._batch()
        b.write_bits(0, RECOVERY_CYCLES)
        self._run(b)

    # ── register helpers used by the probe ──────────────────────────────────
    def read_reg(self, apndp: int, addr: int) -> Txn:
        return self.enqueue(apndp, 1, addr)

    def write_reg(self, apndp: int, addr: int, value: int) -> Txn:
        return self.enqueue(apndp, 0, addr, value)
