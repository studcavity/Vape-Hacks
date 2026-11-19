"""Unit tests for the small arithmetic helpers in host/lb_sync.py (the simulated-device
tests in host/test_lb_sync.py cover the end-to-end sync behaviour)."""
import re

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
        expr = re.sub(r"\(u?int32_t\)", "", expr)         # C casts (LB_NO_TEMP, LB_FW_VERSION)
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


def _words(h):
    """The firmware's own fixed header as the host would read it, built from the header's #defines."""
    return [h["LB_MAGIC0"], h["LB_MAGIC1"], h["LB_FORMAT"], 34, h["LB_FW_VERSION"], 0xABCD1234, 1, 0x200002F8]


def test_header_packing_matches_host_parser():
    """Firmware packs format and version into words; lb_compat unpacks them. Round-trip the real #defines."""
    import lb_compat
    h = _header_defines()
    assert h["LB_FORMAT"] == (h["LB_FORMAT_MAJOR"] << 16) | h["LB_FORMAT_MINOR"]
    p = lb_compat.parse_header(_words(h))
    assert (p.major, p.minor) == (h["LB_FORMAT_MAJOR"], h["LB_FORMAT_MINOR"])
    assert p.fw == (h["LB_FW_MAJOR"], h["LB_FW_MINOR"], h["LB_FW_PATCH"])
    assert p.dirty is True and p.build == 0xABCD1234


def test_fixed_header_words_match_firmware_struct():
    import lb_catalog
    import lb_compat
    import pathlib
    header = pathlib.Path(lb.__file__).resolve().parents[1] / "firmware/lightning_bugs/lb_sync.h"
    body = re.search(r"struct LbSyncBlock \{(.*?)\};", header.read_text(), re.S).group(1)
    fixed = body.split("// ── sync")[0]            # the section marked "never moves"
    names = re.findall(r"^\s*u?int32_t\s+(\w+);", fixed, re.M)
    assert tuple(names) == lb_catalog.HEADER_FIELDS
    assert lb_compat.HEADER_WORDS == len(names)


def test_firmware_is_not_older_than_the_format_it_introduced():
    import lb_catalog
    h = _header_defines()
    assert (h["LB_FW_MAJOR"], h["LB_FW_MINOR"], h["LB_FW_PATCH"]) >= lb_catalog.FIRST_FW


def test_default_beat_period_is_the_hosts_default_tempo():
    """Firmware boots at LB_DEFAULT_PERIOD_US ("120 BPM"); the host's --bpm default must agree."""
    h = _header_defines()
    assert round(60e6 / 120.0) == h["LB_DEFAULT_PERIOD_US"]
    src = pathlib_text("host/lb_sync.py")
    assert 'default=120.0, help="beat tempo (default 120)"' in src


def pathlib_text(rel):
    import pathlib
    return (pathlib.Path(lb.__file__).resolve().parents[1] / rel).read_text()


def test_bit_flags_match_firmware_expressions():
    """power_state and fw_flags bits are literals in the firmware and in the host decoders."""
    import lb_catalog
    fw = pathlib_text("firmware/lightning_bugs/lb_sync.h")
    assert "(lbPower.latched ? 1u : 0u) | (usb ? 2u : 0u)" in fw      # bit0 = low, bit1 = USB
    assert "(LB_BUILD_DIRTY ? 1u : 0u)" in fw                          # fw_flags bit0 = dirty
    blk = type("B", (), {"batt_mv": 3700, "wake_count": 2})()
    for state, low, usb in [(0, False, False), (1, True, False), (2, False, True), (3, True, True)]:
        blk.power_state = state
        d = lb_catalog.decode_power_v1(blk)
        assert (d["low"], d["usb"]) == (low, usb)


def test_chip_ram_size_agrees_between_host_modules():
    import lb_catalog
    assert lb.RAM_SIZE == lb_catalog.PY32F030X8.ram_bytes


def test_tool_defaults_agree():
    """lb_flash, lb_stack and lb_sync each restate the board and probe-clock defaults."""
    import lb_flash
    import lb_stack
    assert lb_flash.DEFAULT_FQBN == lb_stack.DEFAULT_FQBN
    assert f"default={lb_flash.DEFAULT_FREQ:_}" in pathlib_text("host/lb_sync.py")


def test_build_flags_passed_by_tools_exist_in_lb_version_h():
    """-DLB_xxx=... from lb_flash/lb_stack only take effect where lb_version.h has an #ifndef LB_xxx default."""
    ver = pathlib_text("firmware/lightning_bugs/lb_version.h")
    used = set()
    for tool in ("tools/lb_flash.py", "tools/lb_stack.py"):
        used |= set(re.findall(r"-D(LB_\w+)=", pathlib_text(tool)))
    assert {"LB_MODEL_ID", "LB_BUILD_ID", "LB_BUILD_DIRTY"} <= used
    for name in used:
        assert re.search(rf"^#ifndef {name}\b", ver, re.M), f"{name} has no overridable default in lb_version.h"
