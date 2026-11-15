"""Unit tests for the small arithmetic helpers in host/lb_sync.py (the simulated-device
tests in host/test_lb_sync.py cover the end-to-end sync behaviour)."""
import pytest

import lb_sync as lb


@pytest.mark.parametrize("v, want", [
    (0, 0), (1, 1), (0x7FFFFFFF, 2**31 - 1), (0x80000000, -(2**31)),
    (0xFFFFFFFF, -1), (2**32 + 5, 5), (-1, -1),
])
def test_s32(v, want):
    assert lb.s32(v) == want


def test_s64_combines_halves_signed():
    assert lb.s64(1, 0) == 1
    assert lb.s64(0, 1) == 2**32
    assert lb.s64(0xFFFFFFFF, 0xFFFFFFFF) == -1
    assert lb.s64(0, 0x80000000) == -(2**63)


def test_block_layout_matches_firmware_header():
    """Field order is a wire format shared with lb_sync.h; catch accidental reordering."""
    import re
    import pathlib
    header = pathlib.Path(lb.__file__).resolve().parents[1] / "firmware/lightning_bugs/lb_sync.h"
    body = re.search(r"struct LbSyncBlock \{(.*?)\};", header.read_text(), re.S).group(1)
    fields = re.findall(r"^\s*(?:volatile\s+)?u?int32_t\s+(\w+);\s*(?://\s*\[(\d+)\])?",
                        body, re.M)
    assert [f for f, _ in fields] == lb.BLOCK_FIELDS
    assert len(fields) == lb.BLOCK_WORDS
    assert lb.RAM_SIZE == 8 * 1024
