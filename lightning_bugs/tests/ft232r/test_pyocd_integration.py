"""pyOCD's own DebugPort and MEM-AP code driving the simulated target through the FT232R probe:
the closest thing to a real session that needs no hardware."""
import pytest

from pyocd.coresight.ap import MEM_AP
from pyocd.coresight.dap import DebugPort
from pyocd.core.session import Session
from pyocd.probe.debug_probe import DebugProbe

from ft232r.sim import RAM_BASE
from ft232r.test_probe import make_probe

pytestmark = pytest.mark.integration


@pytest.fixture
def ap():
    probe = make_probe(connect=False)
    session = Session(probe, options={"auto_unlock": False, "scan_all_aps": False, "frequency": 250000})
    probe.session = session
    dp = DebugPort(probe, _FakeTarget(session))
    probe.connect(DebugProbe.Protocol.SWD)
    dp.connect()                       # line reset, JTAG->SWD, DPIDR, power-up (pyOCD's own sequence)
    from pyocd.coresight.ap import APv1Address
    ap = MEM_AP(dp, APv1Address(0))
    ap.init()
    ap.probe, ap.sim = probe, probe.target
    return ap


class _FakeTarget:
    def __init__(self, session):
        self.session = session


def test_pyocd_dp_connect_found_the_target(ap):
    assert ap.dp.dpidr.idr == ap.sim.DPIDR
    assert ap.sim.ctrl & 0x50000000 == 0x50000000          # pyOCD powered up debug and system


def test_read_write_word(ap):
    ap.write32(RAM_BASE + 0x40, 0x0BADF00D)
    assert ap.read32(RAM_BASE + 0x40) == 0x0BADF00D
    assert ap.sim.ram[16] == 0x0BADF00D


def test_block_transfers(ap):
    words = [0x10000000 + i for i in range(300)]
    ap.write_memory_block32(RAM_BASE, words)
    assert ap.read_memory_block32(RAM_BASE, 300) == words


def test_memory_access_through_csw(ap):
    ap.write_memory(RAM_BASE, 0x11223344, 32)
    assert ap.read_memory(RAM_BASE, 32) == 0x11223344


def test_lb_sync_runs_unchanged_over_the_ft232r_probe(ap):
    """The same lb_sync.Device code that runs over a Pico probe finds the block and samples the tick."""
    import lb_sync as lb
    tick_addr, block = RAM_BASE + 0x2F8, RAM_BASE + 0x400
    init = [lb.MAGIC0, lb.MAGIC1, lb.VERSION, tick_addr] + [0] * (lb.BLOCK_WORDS - 4)
    base = (block - RAM_BASE) // 4
    ap.sim.ram[base:base + lb.BLOCK_WORDS] = init
    ticks = iter(range(1000, 10**6))
    ap.sim.read_hooks[tick_addr] = lambda: next(ticks)

    dev = lb.Device(ap)
    assert dev.addr == block and dev.tick_addr == tick_addr
    s = dev.sample(burst=4)
    assert 1000 <= s.tick < 1100 and s.rtt_ns > 0
    dev.write("period_us", 123456)
    ap.dp.flush()                                   # writes are queued until the next read or flush, as with any probe
    assert ap.sim.ram[base + lb.W["period_us"]] == 123456
