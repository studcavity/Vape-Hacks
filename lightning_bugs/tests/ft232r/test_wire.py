import pytest

from pyocd_ft232r.swd import header, parity32
from pyocd_ft232r.wire import Batch, Pins


# ─── Pins ────────────────────────────────────────────────────────────────────
def test_default_pins_and_direction_mask():
    p = Pins()
    assert (p.swclk, p.swdio_out, p.swdio_in, p.nreset) == (0, 1, 3, None)
    assert p.direction_mask == 0b0011                     # SWDIO_IN (CTS#) stays an input


def test_nreset_is_an_output():
    assert Pins(nreset=2).direction_mask == 0b0111


@pytest.mark.parametrize("kw", [dict(swclk=8), dict(swclk=-1), dict(swdio_in=1), dict(nreset=0), dict(swdio_out=0)])
def test_bad_pins_rejected(kw):
    with pytest.raises(ValueError):
        Pins(**kw)


def test_parse_pins():
    assert Pins.parse("") == Pins()
    assert Pins.parse("swclk=4, swdio_out=5,swdio_in=6,nreset=2") == Pins(4, 5, 6, 2)
    assert Pins.parse("swdio_in=0x7") == Pins(swdio_in=7)


@pytest.mark.parametrize("text", ["swclk", "clk=1", "swclk=x", "swclk=1;swdio_in=2"])
def test_parse_pins_rejects_garbage(text):
    with pytest.raises(ValueError):
        Pins.parse(text)


# ─── Batch ───────────────────────────────────────────────────────────────────
def test_write_bits_is_lsb_first_two_bytes_per_clock():
    b = Batch(Pins())
    b.write_bits(0b10, 2)                                  # bit0=0, bit1=1
    assert list(b.out) == [0b00, 0b01,  0b10, 0b11]        # [clk low, clk high] each; dio on bit 1


def test_read_bits_releases_swdio_and_clocks():
    b = Batch(Pins())
    b.read_bits(2)
    assert list(b.out) == [0b10, 0b11, 0b10, 0b11]


def test_decode_uses_low_byte_samples_lsb_first():
    pins = Pins()
    b = Batch(pins)
    h = b.read_bits(3)
    samples = bytearray(len(b.out))
    for cycle, bit in enumerate([1, 0, 1]):                # target sends 1,0,1 -> value 0b101
        samples[2 * cycle] = bit << pins.swdio_in
        samples[2 * cycle + 1] = 0xFF                       # high-byte samples must be ignored
    assert b.decode(bytes(samples)) == [0b101] and h == 0


def test_clock_samples_nothing():
    b = Batch(Pins())
    b.clock(2)
    assert b.decode(bytes(len(b.out))) == []


def test_decode_length_mismatch_is_an_error():
    b = Batch(Pins())
    b.read_bits(1)
    with pytest.raises(ValueError):
        b.decode(b"\x00")


def test_nreset_level_is_in_every_byte():
    b = Batch(Pins(nreset=2), nreset_level=1)
    b.write_bits(0, 1)
    assert all(x & 0b100 for x in b.out)
    b = Batch(Pins(nreset=2), nreset_level=0)
    b.write_bits(1, 1)
    assert not any(x & 0b100 for x in b.out)


# ─── SWD request headers (well-known values from every SWD implementation) ───
@pytest.mark.parametrize("apndp, rnw, addr, want", [
    (0, 1, 0x0, 0xA5),     # read DPIDR
    (0, 0, 0x4, 0xA9),     # write CTRL/STAT
    (0, 0, 0x8, 0xB1),     # write SELECT
    (0, 1, 0xC, 0xBD),     # read RDBUFF
    (1, 1, 0xC, 0x9F),     # read DRW
    (1, 0, 0x4, 0x8B),     # write TAR
])
def test_header(apndp, rnw, addr, want):
    assert header(apndp, rnw, addr) == want


@pytest.mark.parametrize("v, want", [(0, 0), (1, 1), (3, 0), (0xFFFFFFFF, 0), (0x7FFFFFFF, 1)])
def test_parity32(v, want):
    assert parity32(v) == want
