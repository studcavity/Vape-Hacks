import pytest

from pyocd_ft232r.transport import MAX_SWD_HZ, MIN_SWD_HZ, CalibrationError, FtdiTransport, calibrate
from pyocd_ft232r.wire import Pins

from ft232r.sim import SimGpio
from ft232r.conftest import Rig


@pytest.mark.parametrize("lag", [0, 1, 2, 3])
def test_calibrate_finds_the_sample_lag(lag):
    pins = Pins()
    gpio = SimGpio(lag=lag)
    gpio._pins = pins
    gpio.configure("x", pins.direction_mask, 500_000, 1 << pins.swdio_out)
    assert calibrate(gpio.exchange, pins) == lag


def test_calibrate_detects_missing_loopback():
    pins = Pins()
    gpio = SimGpio(bridge=False)
    gpio._pins = pins
    gpio.configure("x", pins.direction_mask, 500_000, 1 << pins.swdio_out)
    with pytest.raises(CalibrationError, match="SWDIO_OUT pin"):
        calibrate(gpio.exchange, pins)


def test_calibrate_gives_up_beyond_max_lag():
    pins = Pins()
    gpio = SimGpio(lag=5)
    gpio._pins = pins
    gpio.configure("x", pins.direction_mask, 500_000, 1 << pins.swdio_out)
    with pytest.raises(CalibrationError):
        calibrate(gpio.exchange, pins)


def test_calibrate_with_other_pins_and_nreset_high():
    pins = Pins(swclk=4, swdio_out=5, swdio_in=6, nreset=7)
    gpio = SimGpio(lag=2)
    gpio._pins = pins
    gpio.configure("x", pins.direction_mask, 500_000, 0)
    assert calibrate(gpio.exchange, pins, idle_level=1 << 7) == 2


@pytest.mark.parametrize("lag", [0, 1, 2])
def test_exchange_removes_the_lag(lag):
    """After open(), sample i is the pin state after byte i, whatever the chip's lag."""
    rig = Rig(lag=lag, connect=False)
    assert rig.transport.lag == lag
    out = bytes([0b10, 0b00, 0b10, 0b10, 0b00])          # SWDIO_OUT pattern 1,0,1,1,0 through the bridge
    got = rig.transport.exchange(out)
    assert [(s >> rig.pins.swdio_in) & 1 for s in got] == [1, 0, 1, 1, 0]
    assert len(got) == len(out)


def test_open_configures_pins_clock_and_latency():
    rig = Rig(connect=False)
    g = rig.gpio
    assert g.direction == Pins().direction_mask
    assert g.frequency == 500_000.0                      # 2 bytes per SWD clock at 250 kHz
    assert g.latency == 1


@pytest.mark.parametrize("swd_hz, sample_hz", [
    (1, 2 * MIN_SWD_HZ), (250_000, 500_000), (10_000_000, 2 * MAX_SWD_HZ)])
def test_clock_is_clamped(swd_hz, sample_hz):
    assert FtdiTransport._sample_hz(swd_hz) == sample_hz


def test_set_swd_clock_updates_the_controller():
    rig = Rig(connect=False)
    rig.transport.set_swd_clock(100_000)
    assert rig.gpio.frequency == 200_000.0


def test_close_releases_the_device():
    rig = Rig(connect=False)
    rig.transport.close()
    assert rig.gpio.closed
    rig.transport.close()                                # idempotent
