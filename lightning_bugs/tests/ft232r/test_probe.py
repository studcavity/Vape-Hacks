"""The pyOCD-facing probe and plugin: discovery policy, options, DAP calls, reset."""
import importlib.metadata as md

import pytest
from pyocd.core import exceptions
from pyocd.probe.debug_probe import DebugProbe

from pyocd_ft232r import probe as P
from pyocd_ft232r.transport import FtdiTransport
from pyocd_ft232r.wire import Pins

from ft232r.sim import RAM_BASE, SimGpio, SimTarget

INFO = {"serial": "A50285BI", "url": "ftdi://0x403:0x6001:A50285BI/1", "description": "FT232R USB UART"}


def make_probe(target=None, lag=1, connect=True, env_pins=None, monkeypatch=None):
    target = target or SimTarget()
    gpio = SimGpio(target, lag=lag)

    def factory(url, pins, latency):
        gpio._pins = pins
        return FtdiTransport(url, pins, latency, gpio_factory=lambda: gpio)
    probe = P.FT232RProbe(INFO, factory)
    if env_pins and monkeypatch:
        monkeypatch.setenv("PYOCD_FT232R_PINS", env_pins)
    probe.open()
    if connect:
        probe.connect(DebugProbe.Protocol.SWD)
        probe.swj_sequence(51, (1 << 51) - 1)
        probe.swj_sequence(16, 0xE79E)
        probe.swj_sequence(51, (1 << 51) - 1)
        probe.swj_sequence(8, 0)
    probe.target, probe.gpio = target, gpio
    return probe


# ─── plugin registration and discovery ───────────────────────────────────────
def test_plugin_is_registered_as_an_entry_point():
    eps = {e.name: e.value for e in md.entry_points(group="pyocd.probe")}
    assert eps["ft232r"] == "pyocd_ft232r.probe:FT232RProbePlugin"


def test_pyocd_loads_the_plugin():
    from pyocd.probe.aggregator import PROBE_CLASSES
    assert PROBE_CLASSES["ft232r"] is P.FT232RProbe


def test_plugin_metadata_and_options():
    plugin = P.FT232RProbePlugin()
    assert plugin.name == "ft232r" and plugin.load() is P.FT232RProbe
    assert {o.name for o in plugin.options} == {P.PINS_OPTION, P.SAFE_OPTION, P.LATENCY_OPTION}


@pytest.fixture
def adaptors(monkeypatch):
    devs = [dict(INFO), dict(INFO, serial="B1", url="ftdi://0x403:0x6001:B1/1")]
    monkeypatch.setattr(P, "list_adaptors", lambda: devs)
    monkeypatch.delenv("PYOCD_FT232R_AUTODETECT", raising=False)


def test_not_offered_unless_asked_for(adaptors):
    """A USB-serial adaptor plugged into something else must never be driven by accident."""
    assert P.FT232RProbe.get_all_connected_probes() == []
    assert P.FT232RProbe.get_probe_with_id("A50285BI") is None
    assert P.FT232RProbe.get_probe_with_id("") is None


def test_explicit_selection_by_serial_or_first(adaptors):
    assert P.FT232RProbe.get_probe_with_id("B1", is_explicit=True).unique_id == "B1"
    assert P.FT232RProbe.get_probe_with_id("b1", is_explicit=True).unique_id == "B1"
    assert P.FT232RProbe.get_probe_with_id("", is_explicit=True).unique_id == "A50285BI"
    assert P.FT232RProbe.get_probe_with_id("nope", is_explicit=True) is None
    assert len(P.FT232RProbe.get_all_connected_probes("", is_explicit=True)) == 2


def test_autodetect_env_lists_them(adaptors, monkeypatch):
    monkeypatch.setenv("PYOCD_FT232R_AUTODETECT", "1")
    assert [p.unique_id for p in P.FT232RProbe.get_all_connected_probes()] == ["A50285BI", "B1"]


def test_aggregator_understands_the_ft232r_prefix(adaptors):
    from pyocd.probe.aggregator import DebugProbeAggregator
    (probe,) = DebugProbeAggregator.get_all_connected_probes("ft232r:B1")
    assert probe.unique_id == "B1" and probe.vendor_name == "FTDI"


def test_enumeration_failure_means_no_probes(monkeypatch):
    import pyftdi.ftdi
    monkeypatch.setattr(pyftdi.ftdi.Ftdi, "list_devices", staticmethod(lambda url: (_ for _ in ()).throw(OSError("no libusb"))))
    assert P.list_adaptors() == []


def test_list_adaptors_builds_urls(monkeypatch):
    import pyftdi.ftdi
    from collections import namedtuple
    D = namedtuple("D", "vid pid bus address sn index description")
    monkeypatch.setattr(pyftdi.ftdi.Ftdi, "list_devices", staticmethod(lambda url: [
        (D(0x403, 0x6001, 1, 5, "SER1", 0, "FT232R USB UART"), 1),
        (D(0x403, 0x6001, 2, 10, None, 0, None), 1)]))
    a, b = P.list_adaptors()
    assert a["url"] == "ftdi://0x403:0x6001:SER1/1" and a["serial"] == "SER1"
    assert b["url"] == "ftdi://0x403:0x6001:2:a/1" and b["serial"] == "2:10" and b["description"]


# ─── probe behaviour ─────────────────────────────────────────────────────────
def test_identity_and_capabilities():
    probe = make_probe(connect=False)
    assert probe.description == "FTDI FT232R USB UART" and probe.unique_id == "A50285BI"
    assert DebugProbe.Capability.SWJ_SEQUENCE in probe.capabilities
    assert probe.wire_protocol is None
    probe.connect()
    assert probe.wire_protocol == DebugProbe.Protocol.SWD
    with pytest.raises(ValueError):
        probe.connect(DebugProbe.Protocol.JTAG)


def test_dp_and_ap_access():
    probe = make_probe()
    assert probe.read_dp(0x0) == probe.target.DPIDR
    probe.write_dp(0x4, 0x50000000)
    probe.write_dp(0x8, 0)
    probe.write_ap(0x0, 0x23000012)
    probe.write_ap(0x4, RAM_BASE)
    probe.write_ap_multiple(0xC, [1, 2, 3])
    probe.write_ap(0x4, RAM_BASE)
    assert probe.read_ap_multiple(0xC, 3) == [1, 2, 3]
    assert probe.target.ram[:3] == [1, 2, 3]
    probe.write_ap(0x4, RAM_BASE + 8)
    assert probe.read_ap(0xC) == 3


def test_deferred_reads_run_in_one_exchange():
    probe = make_probe()
    probe.write_dp(0x4, 0x50000000)
    probe.write_ap(0x0, 0x23000012)
    probe.target.ram[0] = 0xCAFE
    probe.flush()
    before = probe.gpio.exchanges
    probe.write_ap(0x4, RAM_BASE)
    cb = probe.read_ap(0xC, now=False)
    assert probe.gpio.exchanges == before          # nothing sent until the result is needed
    assert cb() == 0xCAFE
    assert probe.gpio.exchanges - before == 1
    assert cb() == 0xCAFE                          # and the callback is repeatable


def test_deferred_error_surfaces_from_the_callback():
    probe = make_probe()
    probe.target.fault_count = 1
    cb = probe.read_dp(0x0, now=False)
    with pytest.raises(exceptions.TransferFaultError):
        cb()
    with pytest.raises(exceptions.TransferFaultError):
        cb()
    assert probe.read_dp(0x0) == probe.target.DPIDR


def test_read_ap_multiple_errors_propagate():
    probe = make_probe()
    probe.target.fault_count = 1
    with pytest.raises(exceptions.TransferFaultError):
        probe.read_ap_multiple(0xC, 2)


def test_swd_sequence_return_shape():
    probe = make_probe()
    assert probe.swd_sequence([(8, 0)]) == (0,)
    status, reads = probe.swd_sequence([(4, 0), (8,)])
    assert status == 0 and len(reads) == 1 and len(reads[0]) == 1


def test_set_clock_before_and_after_open():
    probe = make_probe(connect=False)
    probe.set_clock(100_000)
    assert probe.gpio.frequency == 200_000.0
    p2 = P.FT232RProbe(INFO)
    p2.set_clock(123_000)                          # not open yet: just remembered
    assert p2._clock_hz == 123_000.0


def test_close_parks_the_lines_and_releases_the_device():
    probe = make_probe()
    probe.write_dp(0x4, 1)                         # queued
    probe.close()
    assert probe.target.ctrl == 1                  # flushed before closing
    assert probe.gpio.closed and not probe.is_open
    last = probe.gpio.sent[-1]
    assert last & (1 << probe.pins.swdio_out) and not last & (1 << probe.pins.swclk)


# ─── options and reset ───────────────────────────────────────────────────────
def test_pins_from_environment(monkeypatch):
    probe = make_probe(connect=False, env_pins="swclk=4,swdio_out=5,swdio_in=6", monkeypatch=monkeypatch)
    assert probe.pins == Pins(4, 5, 6)


def test_reset_needs_an_nreset_pin():
    probe = make_probe()
    with pytest.raises(exceptions.ProbeError, match="nRESET"):
        probe.assert_reset(True)


def test_reset_toggles_the_nreset_pin(monkeypatch):
    monkeypatch.setattr(P, "sleep", lambda s: None)
    probe = make_probe(connect=False, env_pins="nreset=2", monkeypatch=monkeypatch)
    nrst = 1 << 2
    assert probe.gpio.sent[-1] & nrst              # released (high) while idle
    probe.assert_reset(True)
    assert probe.is_reset_asserted() and not probe.gpio.sent[-1] & nrst
    probe.assert_reset(False)
    assert not probe.is_reset_asserted() and probe.gpio.sent[-1] & nrst
    probe.reset()
    assert probe.gpio.sent[-1] & nrst and not probe.is_reset_asserted()
