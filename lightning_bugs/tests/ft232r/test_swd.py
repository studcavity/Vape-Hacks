"""SwdLink against the simulated SW-DP (through the real FtdiTransport and wire encoding)."""
import pytest
from pyocd.core import exceptions

from pyocd_ft232r.swd import RDBUFF, WAIT_RETRIES
from ft232r.sim import RAM_BASE

DP, AP = 0, 1
CSW, TAR, DRW = 0x0, 0x4, 0xC          # A[3:2] within AP bank 0


def read(link, apndp, addr):
    t = link.read_reg(apndp, addr)
    link.flush()
    return t.result


def setup_mem_ap(rig):
    link = rig.link
    link.write_reg(DP, 0x4, 0x50000000)                    # power up
    link.write_reg(DP, 0x8, 0x00000000)                    # SELECT bank 0
    link.write_reg(AP, CSW, 0x23000012)                    # 32-bit, auto-increment
    link.flush()


def test_dpidr_after_switch_sequence(rig):
    assert read(rig.link, DP, 0x0) == rig.target.DPIDR
    assert rig.target.swd_enabled and rig.target.line_resets == 2


def test_target_not_in_swd_mode_gives_protocol_error(make_rig):
    rig = make_rig(connect=False)
    t = rig.link.read_reg(DP, 0x0)
    with pytest.raises(exceptions.TransferError, match="protocol error"):
        rig.link.flush()
    assert t.error is not None and not t.done


def test_dp_writes_land_in_target_registers(rig):
    rig.link.write_reg(DP, 0x4, 0x50000000)
    rig.link.write_reg(DP, 0x8, 0x000000F0)
    rig.link.flush()
    assert rig.target.ctrl == 0x50000000 and rig.target.select == 0xF0
    assert read(rig.link, DP, 0x4) & 0xA0000000 == 0xA0000000     # power-up ACK bits mirror the requests


def test_ap_write_then_posted_read(rig):
    setup_mem_ap(rig)
    rig.link.write_reg(AP, TAR, RAM_BASE + 0x10)
    rig.link.write_reg(AP, DRW, 0xDEADBEEF)
    rig.link.flush()
    assert rig.target.ram[4] == 0xDEADBEEF

    rig.link.write_reg(AP, TAR, RAM_BASE + 0x10)
    rig.link.read_reg(AP, DRW)                             # posted: result of the *previous* read
    last = rig.link.read_reg(DP, RDBUFF)
    rig.link.flush()
    assert last.result == 0xDEADBEEF


def test_read32_is_one_usb_round_trip(rig):
    """TAR write + DRW read + RDBUFF read run as a single exchange: the sync tool's latency depends on it."""
    setup_mem_ap(rig)
    rig.target.ram[0] = 0x12345678
    before = rig.gpio.exchanges
    rig.link.write_reg(AP, TAR, RAM_BASE)
    rig.link.read_reg(AP, DRW)
    last = rig.link.read_reg(DP, RDBUFF)
    rig.link.flush()
    assert last.result == 0x12345678
    assert rig.gpio.exchanges - before == 1


def test_safe_mode_uses_one_exchange_per_transaction(make_rig):
    rig = make_rig(safe=True)
    setup_mem_ap(rig)
    rig.target.ram[0] = 7
    before = rig.gpio.exchanges
    rig.link.write_reg(AP, TAR, RAM_BASE)
    rig.link.read_reg(AP, DRW)
    last = rig.link.read_reg(DP, RDBUFF)
    assert last.result == 7
    assert rig.gpio.exchanges - before == 3


def test_auto_increment_block_read_spans_many_batches(rig):
    setup_mem_ap(rig)
    n = 200                                                # more than MAX_BATCH transactions
    rig.target.ram[:n] = [0x1000 + i for i in range(n)]
    rig.link.write_reg(AP, TAR, RAM_BASE)
    reads = [rig.link.read_reg(AP, DRW) for _ in range(n)]
    last = rig.link.read_reg(DP, RDBUFF)
    rig.link.flush()
    assert [t.result for t in reads[1:]] + [last.result] == [0x1000 + i for i in range(n)]


def test_block_write(rig):
    setup_mem_ap(rig)
    rig.link.write_reg(AP, TAR, RAM_BASE + 0x40)
    for i in range(100):
        rig.link.write_reg(AP, DRW, 0xA000 + i)
    rig.link.flush()
    assert rig.target.ram[16:116] == [0xA000 + i for i in range(100)]


def test_wait_is_retried(rig):
    rig.target.wait_count = 5
    assert read(rig.link, DP, 0x0) == rig.target.DPIDR
    assert rig.target.wait_count == 0


def test_wait_covering_the_whole_tail_replays_it_in_order(rig):
    """TAR, DRW, DRW all answered WAIT: nothing ran, so the replay is safe and exactly-once."""
    setup_mem_ap(rig)
    rig.target.writes.clear()
    rig.target.wait_count = 3
    rig.link.write_reg(AP, TAR, RAM_BASE + 0x20)
    rig.link.write_reg(AP, DRW, 0xAAAA0001)
    rig.link.write_reg(AP, DRW, 0xAAAA0002)
    rig.link.flush()
    assert rig.target.writes == [(RAM_BASE + 0x20, 0xAAAA0001), (RAM_BASE + 0x24, 0xAAAA0002)]


def test_wait_in_the_middle_is_reported_not_replayed(rig):
    """A WAIT followed by accepted frames cannot be replayed (it would reorder/duplicate writes)."""
    setup_mem_ap(rig)
    rig.target.writes.clear()
    orig = rig.target._header_done
    n = {"i": 0}

    def hook():
        n["i"] += 1
        if n["i"] == 2:                                    # the first DRW write
            rig.target.wait_count = 1
        orig()
    rig.target._header_done = hook
    rig.link.write_reg(AP, TAR, RAM_BASE + 0x20)
    rig.link.write_reg(AP, DRW, 0xAAAA0001)
    rig.link.write_reg(AP, DRW, 0xAAAA0002)
    with pytest.raises(exceptions.TransferError, match="cannot replay"):
        rig.link.flush()
    assert (RAM_BASE + 0x20, 0xAAAA0001) not in rig.target.writes   # and nothing ran twice
    assert len(rig.target.writes) == len(set(rig.target.writes))


def test_wait_forever_raises_timeout(rig):
    rig.target.wait_count = 10_000
    t = rig.link.read_reg(DP, 0x0)
    with pytest.raises(exceptions.TransferTimeoutError):
        rig.link.flush()
    assert t.error is not None
    assert WAIT_RETRIES < 10_000


def test_fault_raises_and_the_line_recovers(rig):
    rig.target.fault_count = 1
    with pytest.raises(exceptions.TransferFaultError):
        read(rig.link, DP, 0x0)
    assert read(rig.link, DP, 0x0) == rig.target.DPIDR     # idle flush left the target in sync
    assert rig.target.line_resets == 2                     # ... without needing another line reset


def test_failed_write_does_not_desync_the_target_even_with_hostile_data(rig):
    """After a FAULT the 33 data bits we clock blind must not be taken for requests."""
    setup_mem_ap(rig)
    rig.target.fault_count = 1
    rig.link.write_reg(AP, TAR, RAM_BASE)
    with pytest.raises(exceptions.TransferFaultError):
        rig.link.flush()
    for hostile in (0xFFFFFFFF, 0xA5A5A5A5, 0x00000085):
        rig.target.fault_count = 1
        rig.link.write_reg(AP, TAR, hostile)
        with pytest.raises(exceptions.TransferFaultError):
            rig.link.flush()
    assert rig.target.line_resets == 2
    assert read(rig.link, DP, 0x0) == rig.target.DPIDR


def test_bad_read_parity_is_a_probe_error(rig):
    rig.target.flip_read_parity = 1
    with pytest.raises(exceptions.ProbeError, match="parity"):
        read(rig.link, DP, 0x0)
    assert read(rig.link, DP, 0x0) == rig.target.DPIDR


def test_results_before_a_failure_stay_valid(rig):
    a = rig.link.read_reg(DP, 0x0)
    rig.target.fault_count = 0
    orig = rig.target._header_done
    n = {"i": 0}

    def hook():
        n["i"] += 1
        if n["i"] == 2:
            rig.target.fault_count = 1
        orig()
    rig.target._header_done = hook
    b = rig.link.read_reg(DP, 0x4)
    c = rig.link.read_reg(DP, 0x8)
    with pytest.raises(exceptions.TransferFaultError):
        rig.link.flush()
    assert a.done and a.result == rig.target.DPIDR and b.error is not None and c.error is not None


def test_swj_and_swd_sequences(rig):
    reads = rig.link.swd_sequence([(8, 0xA5), (4,), (8, 0x00)])
    assert len(reads) == 1 and len(reads[0]) == 1
    rig.link.swj_sequence(130, (1 << 130) - 1)             # longer than one 64-bit chunk
    rig.link.swj_sequence(2, 0)                            # the target counts a reset when the ones end
    assert rig.target.line_resets >= 3
