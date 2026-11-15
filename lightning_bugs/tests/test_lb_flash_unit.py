"""Unit tests for the pure safety-check logic in tools/lb_flash.py (no arduino-cli, no pyocd)."""
import hashlib

import pytest

import lb_flash


# ─── strip_comments ──────────────────────────────────────────────────────────
def test_strip_comments_removes_line_comment():
    assert lb_flash.strip_comments("a(); // PA13\nb();").splitlines() == ["a(); ", "b();"]


def test_strip_comments_block_comment_keeps_line_numbers():
    out = lb_flash.strip_comments("x\n/* PA13\n PA14 */\ny")
    assert out.splitlines() == ["x", "", "", "y"]


# ─── source rules ────────────────────────────────────────────────────────────
@pytest.fixture
def sketch(tmp_path, monkeypatch):
    """Point lb_flash at a scratch sketch dir; returns a writer for files in it."""
    monkeypatch.setattr(lb_flash, "SKETCH_DIR", tmp_path)
    monkeypatch.setattr(lb_flash, "ROOT", tmp_path)

    def write(name, text):
        (tmp_path / name).write_text(text)
    return write


@pytest.mark.parametrize("line, why", [
    ("pinMode(PA13, OUTPUT);", "PA13/PA14"),
    ("digitalWrite(PA14, HIGH);", "PA13/PA14"),
    ("GPIOA->MODER = 0;", "GPIOA mode"),
    ("GPIOA -> AFR0 |= 1;", "GPIOA mode"),
    ("SCB->SCR |= SCB_SCR_SLEEPDEEP_Msk;", "deep-sleep"),
    ("HAL_PWR_EnterSTOPMode(0, 0);", "STOP/STANDBY"),
    ("FLASH->OPTKEYR = 1;", "flash/option-byte"),
    ("HAL_FLASHEx_OBProgram(&ob);", "flash/option-byte"),
    ("RCC->CFGR = 0;", "clock configuration"),
    ("SystemClock_Config();", "clock configuration"),
    ("DBGMCU->CR = 0;", "debug-MCU"),
])
def test_dangerous_source_is_flagged(sketch, line, why):
    sketch("a.ino", f"void f() {{\n  {line}\n}}\n")
    problems = lb_flash.check_source()
    assert len(problems) == 1
    assert why in problems[0]
    assert "a.ino:2:" in problems[0]            # reports the right line


@pytest.mark.parametrize("line", [
    "pinMode(PA1, OUTPUT);",
    "int PA130 = 3;",                            # \b: not PA13
    "digitalWrite(PA2, HIGH);",
    "// pinMode(PA13, OUTPUT);",                 # comments are ignored
    "/* GPIOA->MODER = 0; */",
])
def test_safe_source_is_not_flagged(sketch, line):
    sketch("a.ino", f"void f() {{\n  {line}\n}}\n")
    assert lb_flash.check_source() == []


def test_allow_marker_waives_rule_on_that_line_only(sketch):
    sketch("a.ino", f"pinMode(PA13, INPUT); // {lb_flash.ALLOW}\npinMode(PA14, INPUT);\n")
    problems = lb_flash.check_source()
    assert len(problems) == 1 and "a.ino:2:" in problems[0]


def test_non_source_files_are_ignored(sketch):
    sketch("notes.txt", "PA13 PA14 SLEEPDEEP\n")
    sketch("b.h", "#define X 1\n")
    assert lb_flash.check_source() == []


def test_all_source_extensions_are_scanned(sketch):
    for ext in ("ino", "h", "c", "cpp", "hpp"):
        sketch(f"f.{ext}", "PA13\n")
    assert len(lb_flash.check_source()) == 5


def test_committed_firmware_passes_its_own_safety_check():
    """The real sketch in the repo must stay clean (guards against rule/firmware drift)."""
    assert lb_flash.check_source() == []


# ─── binary checks ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(lb_flash.UNLOCK_KEYS))
def test_binary_with_unlock_key_is_rejected(tmp_path, name):
    binf = tmp_path / "fw.bin"
    binf.write_bytes(b"\x00" * 16 + lb_flash.UNLOCK_KEYS[name] + b"\xff" * 16)
    problems = lb_flash.check_binary(None, binf)
    assert len(problems) == 1 and name in problems[0]


def test_clean_binary_passes(tmp_path):
    binf = tmp_path / "fw.bin"
    binf.write_bytes(bytes(range(256)) * 4)
    assert lb_flash.check_binary(None, binf) == []


def test_unlock_keys_are_little_endian_of_documented_values():
    assert lb_flash.UNLOCK_KEYS["FLASH_KEY1 0x45670123"] == (0x45670123).to_bytes(4, "little")
    assert lb_flash.UNLOCK_KEYS["OPT_KEY2   0x4C5D6E7F"] == (0x4C5D6E7F).to_bytes(4, "little")


@pytest.mark.parametrize("sym, bad", [
    ("HAL_FLASHEx_OBProgram", True),
    ("HAL_FLASH_OB_Launch", True),
    ("HAL_PWR_EnterSTOPMode", True),
    ("HAL_PWR_EnterSTANDBYMode", True),
    ("HAL_RCC_OscConfig", False),                # the core links these into every sketch
    ("HAL_RCC_ClockConfig", False),
])
def test_binary_symbol_rule(sym, bad):
    import re
    assert bool(re.search(lb_flash.BINARY_SYMBOL_RULES, f"08001234 T {sym}")) is bad


# ─── canary record helpers ───────────────────────────────────────────────────
def test_sha_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert lb_flash.sha(f) == hashlib.sha256(b"hello").hexdigest()


def test_load_canary_missing_or_corrupt_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(lb_flash, "CANARY_FILE", tmp_path / ".lb_canary.json")
    assert lb_flash.load_canary() == {}
    (tmp_path / ".lb_canary.json").write_text("{not json")
    assert lb_flash.load_canary() == {}


def test_load_canary_reads_record(tmp_path, monkeypatch):
    p = tmp_path / ".lb_canary.json"
    p.write_text('{"abc": {"bin": "x.bin"}}')
    monkeypatch.setattr(lb_flash, "CANARY_FILE", p)
    assert lb_flash.load_canary() == {"abc": {"bin": "x.bin"}}
