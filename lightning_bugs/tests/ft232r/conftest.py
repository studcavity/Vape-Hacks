import pytest

from pyocd_ft232r.swd import SwdLink
from pyocd_ft232r.transport import FtdiTransport
from pyocd_ft232r.wire import Pins

from ft232r.sim import SimGpio, SimTarget, make_gpio_factory


class Rig:
    """A SimTarget behind a SimGpio behind the real FtdiTransport and SwdLink."""

    def __init__(self, lag=1, bridge=True, pins=None, safe=False, connect=True):
        self.pins = pins or Pins()
        self.target = SimTarget()
        self.gpio = SimGpio(self.target, lag=lag, bridge=bridge)
        self.transport = FtdiTransport("ftdi://sim", self.pins, gpio_factory=make_gpio_factory(self.gpio, self.pins))
        self.transport.open(250_000, 0)
        self.link = SwdLink(self.transport, self.pins, safe=safe)
        if connect:
            self.attach()

    def attach(self):
        """Line reset, JTAG-to-SWD switch, line reset, idle: the sequence pyOCD sends."""
        self.link.swj_sequence(51, (1 << 51) - 1)
        self.link.swj_sequence(16, 0xE79E)
        self.link.swj_sequence(51, (1 << 51) - 1)
        self.link.swj_sequence(8, 0)


@pytest.fixture
def rig():
    return Rig()


@pytest.fixture
def make_rig():
    return Rig
