"""pyOCD DebugProbe and plugin for SWD over an FT232R (see wire.py for the wiring).

Selecting it: FT232R adaptors are ordinary USB-serial devices, so the probe is only offered when you
ask for it, so that a tool run without `--probe` never wiggles the pins of a serial adaptor that is
plugged into something else:

    pyocd list -u ft232r:            # (or any tool's --probe/-u)   first FT232R
    ... -u ft232r:A50285BI           # a specific adaptor, by USB serial number
    PYOCD_FT232R_AUTODETECT=1 ...    # list FT232Rs like any other probe

Options (pyocd -O name=value, or the environment variable in brackets):
    ft232r.pins          swclk=0,swdio_out=1,swdio_in=3[,nreset=2]   [PYOCD_FT232R_PINS]
    ft232r.safe          one transaction per USB round trip           [PYOCD_FT232R_SAFE=1]
    ft232r.latency_timer FTDI latency timer in ms (default 1)
"""
from __future__ import annotations

import logging
import os
from time import sleep
from typing import Callable

from pyocd.core import exceptions
from pyocd.core.options import OptionInfo
from pyocd.core.plugin import Plugin
from pyocd.probe.debug_probe import DebugProbe

from .swd import RDBUFF, SwdLink, Txn
from .transport import PID, VID, FtdiTransport
from .wire import Pins

LOG = logging.getLogger(__name__)

PINS_OPTION = "ft232r.pins"
SAFE_OPTION = "ft232r.safe"
LATENCY_OPTION = "ft232r.latency_timer"
DP, AP = 0, 1


def _opt(session, name, env, default):
    if session is not None:
        v = session.options.get(name)
        if v not in (None, "", False):
            return v
    return os.environ.get(env) or default


def autodetect_enabled() -> bool:
    return os.environ.get("PYOCD_FT232R_AUTODETECT") == "1"


def list_adaptors() -> list[dict]:
    """FT232R devices on the bus: [{'serial', 'url', 'description'}]."""
    try:
        from pyftdi.ftdi import Ftdi
        found = Ftdi.list_devices(f"ftdi://{VID:#x}:{PID:#x}/1")
    except Exception as e:                  # no libusb, no permission, ...
        LOG.debug("FT232R enumeration failed: %s", e)
        return []
    out = []
    for desc, _ifaces in found:
        if desc.sn:
            url, serial = f"ftdi://{VID:#x}:{PID:#x}:{desc.sn}/1", desc.sn
        else:
            url, serial = f"ftdi://{VID:#x}:{PID:#x}:{desc.bus:x}:{desc.address:x}/1", f"{desc.bus}:{desc.address}"
        out.append({"serial": serial, "url": url, "description": desc.description or "FT232R USB UART"})
    return out


class FT232RProbe(DebugProbe):
    def __init__(self, info: dict, transport_factory: Callable | None = None):
        super().__init__()
        self._info = info
        self._factory = transport_factory or (lambda url, pins, latency: FtdiTransport(url, pins, latency))
        self._transport = None
        self._link: SwdLink | None = None
        self._is_open = False
        self._connected = False
        self._clock_hz = 250_000.0
        self._reset = False
        self.pins = Pins()

    # ── discovery ────────────────────────────────────────────────────────────
    @classmethod
    def get_all_connected_probes(cls, unique_id=None, is_explicit=False):
        if not (is_explicit or autodetect_enabled()):
            return []
        return [cls(i) for i in list_adaptors()]

    @classmethod
    def get_probe_with_id(cls, unique_id, is_explicit=False):
        if not (is_explicit or autodetect_enabled()):
            return None
        devices = list_adaptors()
        if unique_id:
            devices = [d for d in devices if d["serial"].lower() == unique_id.lower()]
        elif not is_explicit:
            return None
        return cls(devices[0]) if devices else None

    # ── DebugProbe properties ────────────────────────────────────────────────
    @property
    def description(self): return f"{self.vendor_name} {self.product_name}"
    @property
    def vendor_name(self): return "FTDI"
    @property
    def product_name(self): return self._info["description"]
    @property
    def supported_wire_protocols(self): return [DebugProbe.Protocol.DEFAULT, DebugProbe.Protocol.SWD]
    @property
    def unique_id(self): return self._info["serial"]
    @property
    def wire_protocol(self): return DebugProbe.Protocol.SWD if self._connected else None
    @property
    def is_open(self): return self._is_open
    @property
    def capabilities(self): return {DebugProbe.Capability.SWJ_SEQUENCE, DebugProbe.Capability.SWD_SEQUENCE}

    # ── lifecycle ────────────────────────────────────────────────────────────
    def open(self):
        s = self.session
        self.pins = Pins.parse(_opt(s, PINS_OPTION, "PYOCD_FT232R_PINS", ""))
        safe = bool(_opt(s, SAFE_OPTION, "PYOCD_FT232R_SAFE", False)) and \
            str(_opt(s, SAFE_OPTION, "PYOCD_FT232R_SAFE", "")) not in ("0", "false", "False")
        latency = int(_opt(s, LATENCY_OPTION, "PYOCD_FT232R_LATENCY", 1))
        idle = (1 << self.pins.nreset) if self.pins.nreset is not None else 0
        self._transport = self._factory(self._info["url"], self.pins, latency)
        self._transport.open(self._clock_hz, idle)
        self._link = SwdLink(self._transport, self.pins, nreset_level=1, safe=safe)
        self._is_open = True

    def close(self):
        try:
            if self._link is not None:
                try:
                    self._link.flush()
                finally:
                    self._link.idle_line()
        finally:
            if self._transport is not None:
                self._transport.close()
            self._transport = self._link = None
            self._is_open = False

    def connect(self, protocol=None):
        if protocol not in (None, DebugProbe.Protocol.DEFAULT, DebugProbe.Protocol.SWD):
            raise ValueError(f"unsupported wire protocol {protocol}")
        self._connected = True              # pyOCD sends the line reset / SWJ switch via swj_sequence()

    def disconnect(self):
        if self._link is not None:
            self._link.flush()
        self._connected = False

    def set_clock(self, frequency):
        self._clock_hz = float(frequency)
        if self._transport is not None:
            self._link.flush()
            self._transport.set_swd_clock(self._clock_hz)

    # ── reset ────────────────────────────────────────────────────────────────
    def assert_reset(self, asserted):
        if self.pins.nreset is None:
            raise exceptions.ProbeError("FT232R: no nRESET pin configured (set ft232r.pins=...,nreset=N)")
        self._link.flush()
        self._link.nreset_level = 0 if asserted else 1
        self._link.idle_line()
        self._reset = bool(asserted)

    def is_reset_asserted(self):
        return self._reset

    def reset(self):
        self.assert_reset(True)
        sleep(self.session.options.get("reset.hold_time") if self.session else 0.02)
        self.assert_reset(False)
        sleep(self.session.options.get("reset.post_delay") if self.session else 0.1)

    # ── sequences ────────────────────────────────────────────────────────────
    def swj_sequence(self, length, bits):
        self._link.swj_sequence(length, bits)

    def swd_sequence(self, sequences):
        reads = self._link.swd_sequence(sequences)
        return (0, reads) if reads else (0,)

    def flush(self):
        self._link.flush()

    # ── DAP access ───────────────────────────────────────────────────────────
    def _result(self, txn: Txn, now: bool):
        def get():
            if txn.error is not None:
                raise txn.error
            if not txn.done:
                self._link.flush()
            if txn.error is not None:
                raise txn.error
            return txn.result
        return get() if now else get

    def read_dp(self, addr, now=True):
        return self._result(self._link.read_reg(DP, addr), now)

    def write_dp(self, addr, data):
        self._link.write_reg(DP, addr, data)

    def read_ap(self, addr, now=True):
        # AP reads are posted: the first read returns the previous value, RDBUFF returns this one.
        self._link.read_reg(AP, addr)
        return self._result(self._link.read_reg(DP, RDBUFF), now)

    def write_ap(self, addr, data):
        self._link.write_reg(AP, addr, data)

    def read_ap_multiple(self, addr, count=1, now=True):
        txns = [self._link.read_reg(AP, addr) for _ in range(count)]
        last = self._link.read_reg(DP, RDBUFF)

        def get():
            if any(t.error for t in txns + [last]):
                raise next(t.error for t in txns + [last] if t.error)
            if not last.done:
                self._link.flush()
            for t in txns + [last]:
                if t.error is not None:
                    raise t.error
            return [t.result for t in txns[1:]] + [last.result]
        return get() if now else get

    def write_ap_multiple(self, addr, values):
        for v in values:
            self._link.write_reg(AP, addr, v)


class FT232RProbePlugin(Plugin):
    def load(self): return FT232RProbe

    @property
    def name(self): return "ft232r"

    @property
    def description(self): return "FTDI FT232R USB-UART in bit-bang mode (SWD)"

    @property
    def options(self):
        return [
            OptionInfo(PINS_OPTION, str, "", "FT232R pins: swclk=0,swdio_out=1,swdio_in=3[,nreset=N] "
                                             "(env PYOCD_FT232R_PINS)."),
            OptionInfo(SAFE_OPTION, bool, False, "FT232R: one SWD transaction per USB round trip "
                                                 "(slow; never clocks a frame past an error)."),
            OptionInfo(LATENCY_OPTION, int, 1, "FT232R: FTDI latency timer in ms."),
        ]
