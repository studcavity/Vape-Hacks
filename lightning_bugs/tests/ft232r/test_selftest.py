import pytest

from pyocd_ft232r.__main__ import main
from pyocd_ft232r.transport import FtdiTransport

from ft232r.sim import SimGpio, make_gpio_factory

DEV = {"serial": "A1", "url": "ftdi://x", "description": "FT232R USB UART"}


def factory(bridge=True, lag=1):
    def make(url, pins):
        gpio = SimGpio(lag=lag, bridge=bridge)
        return FtdiTransport(url, pins, gpio_factory=make_gpio_factory(gpio, pins))
    return make


def test_list(capsys):
    assert main([], adaptors=[DEV]) == 0
    assert "A1" in capsys.readouterr().out
    assert main([], adaptors=[]) == 1


def test_check_passes_with_loopback(capsys):
    assert main(["check"], adaptors=[DEV], transport_factory=factory(lag=2)) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK") and "lag 2" in out


def test_check_fails_without_the_bridge(capsys):
    assert main(["check"], adaptors=[DEV], transport_factory=factory(bridge=False)) == 2
    assert "FAIL" in capsys.readouterr().out


@pytest.mark.parametrize("devices, serial", [([], None), ([DEV, dict(DEV, serial="B")], None), ([DEV], "nope")])
def test_check_needs_exactly_one_adaptor(devices, serial, capsys):
    argv = ["check"] + ([serial] if serial else [])
    assert main(argv, adaptors=devices, transport_factory=factory()) == 1
