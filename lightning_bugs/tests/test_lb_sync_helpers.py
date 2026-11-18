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
    assert all(int(idx) == lb.W[f] for f, idx in fields), "a [n] index comment is wrong"
    assert len(fields) == lb.BLOCK_WORDS
    assert lb.RAM_SIZE == 8 * 1024


def _header_defines():
    """The numeric #defines of lb_sync.h / lb_power_policy.h / lb_version.h, evaluated."""
    import re
    import pathlib
    fw = pathlib.Path(lb.__file__).resolve().parents[1] / "firmware/lightning_bugs"
    text = "\n".join((fw / n).read_text() for n in ("lb_sync.h", "lb_power_policy.h", "lb_version.h"))
    defs = {}
    for name, expr in re.findall(r"^#define\s+(LB_\w+)\s+(.+?)\s*(?://.*)?$", text, re.M):
        expr = re.sub(r"\(int32_t\)", "", expr)          # LB_NO_TEMP's cast
        expr = re.sub(r"(0x[0-9A-Fa-f]+|\d+)u\b", r"\1", expr)
        try:
            defs[name] = eval(expr, {}, dict(defs))      # our own checked-in header, constants only
        except Exception:
            pass                                         # not a plain constant expression
    return defs


def test_header_constants_match_firmware():
    """Magic, format version and sentinels are duplicated by hand in Python; they must not drift."""
    import lb_catalog
    d = _header_defines()
    assert lb.MAGIC0 == d["LB_MAGIC0"]
    assert lb.MAGIC1 == d["LB_MAGIC1"] & 0xFFFFFFFF
    assert lb.FORMAT_MAJOR == d["LB_FORMAT_MAJOR"]
    newest = max((s for s in lb_catalog.FORMATS.specs if not s.legacy), key=lambda s: (s.major, s.minor))
    assert (newest.major, newest.minor) == (d["LB_FORMAT_MAJOR"], d["LB_FORMAT_MINOR"]), \
        "newest FormatSpec in lb_catalog.FORMATS differs from the firmware's LB_FORMAT_*"
    assert lb_catalog.NO_TEMP == d["LB_NO_TEMP"] - (1 << 32 if d["LB_NO_TEMP"] >= 1 << 31 else 0)
    assert lb.LOW_BATT_MV == d["LB_LOW_MV"]
    assert lb_catalog.DEFAULT_MODEL == d["LB_MODEL_ID"], "firmware's default LB_MODEL_ID != host DEFAULT_MODEL"
