"""Integration tests: run tools/lb_flash.py end to end against fake arduino-cli / pyocd.

Subprocess tests exercise the real CLI (argument parsing, exit codes, files written). The flash
success paths run in-process with sleeps and the SWD reconnect stubbed, because the real flow waits
~35 s and needs a probe. Nothing here touches hardware."""
import argparse
import json
import subprocess
import sys

import pytest

import lb_flash

pytestmark = pytest.mark.integration


def cli(tree, *args, env=None, input=None):
    import os
    return subprocess.run([sys.executable, str(tree / "tools" / "lb_flash.py"), *args],
                          capture_output=True, text=True, env={**os.environ, **(env or {})},
                          input=input, timeout=60)


# ─── check ───────────────────────────────────────────────────────────────────
def test_cli_check_passes_on_committed_sketch(tree):
    r = cli(tree, "check")
    assert r.returncode == 0 and "source safety check: ok" in r.stdout


def test_cli_check_fails_on_dangerous_sketch(tree):
    ino = tree / "firmware" / "lightning_bugs" / "lightning_bugs.ino"
    ino.write_text(ino.read_text() + "\nvoid evil() { pinMode(PA13, OUTPUT); }\n")
    r = cli(tree, "check")
    assert r.returncode == 1
    assert "SAFETY CHECK FAILED" in r.stdout and "PA13/PA14" in r.stdout and "lightning_bugs.ino:" in r.stdout


# ─── build ───────────────────────────────────────────────────────────────────
def test_cli_build_invokes_arduino_cli_and_passes(tree, fakebin):
    r = cli(tree, "--fqbn", "X:Y:Z", "build")
    assert r.returncode == 0, r.stdout + r.stderr
    (call,) = fakebin()
    assert call[:2] == ["arduino-cli", "compile"]
    assert call[call.index("--fqbn") + 1] == "X:Y:Z"
    assert call[call.index("--output-dir") + 1] == str(tree / "build")
    assert "binary safety check: ok (4 bytes)" in r.stdout


def test_cli_build_stops_before_compiling_when_source_check_fails(tree, fakebin):
    (tree / "firmware" / "lightning_bugs" / "x.h").write_text("SCB->SCR |= SLEEPDEEP;\n")
    assert cli(tree, "build").returncode == 1
    assert fakebin() == [], "must not compile unsafe source"


def test_cli_build_reports_compile_failure(tree, fakebin):
    r = cli(tree, "build", env={"FAKE_BUILD_FAIL": "1"})
    assert r.returncode == 1 and "build failed" in r.stdout


def test_cli_build_reports_missing_output(tree, fakebin):
    r = cli(tree, "build", env={"FAKE_NO_BIN": "1"})
    assert r.returncode == 1 and "not found" in r.stdout


def test_cli_build_rejects_binary_with_flash_unlock_key(tree, fakebin):
    r = cli(tree, "build", env={"FAKE_BIN_HEX": "00" + lb_flash.UNLOCK_KEYS["FLASH_KEY1 0x45670123"].hex()})
    assert r.returncode == 1
    assert "BINARY SAFETY CHECK FAILED" in r.stdout and "FLASH_KEY1" in r.stdout


# ─── flash (CLI paths that stop before touching a probe) ─────────────────────
def test_cli_flash_refuses_sealed_unit_without_canary_pass(tree, fakebin):
    r = cli(tree, "flash", "--yes")
    assert r.returncode == 1 and "has not passed on a canary" in r.stdout
    assert not any(c[0] == "pyocd" for c in fakebin()), "pyocd must not run"
    assert not (tree / ".lb_canary.json").exists()


def test_cli_flash_requires_pyocd(tree, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    r = subprocess.run([sys.executable, str(tree / "tools" / "lb_flash.py"), "flash"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "pyocd not found" in r.stdout


# ─── flash (in-process, sleeps and SWD reconnect stubbed) ────────────────────
@pytest.fixture
def flasher(tree, fakebin, monkeypatch):
    monkeypatch.setattr(lb_flash, "ROOT", tree)
    monkeypatch.setattr(lb_flash, "SKETCH_DIR", tree / "firmware" / "lightning_bugs")
    monkeypatch.setattr(lb_flash, "BUILD_DIR", tree / "build")
    monkeypatch.setattr(lb_flash, "CANARY_FILE", tree / ".lb_canary.json")
    monkeypatch.setattr(lb_flash.time, "sleep", lambda s: None)
    verifies = []
    monkeypatch.setattr(lb_flash, "verify_connect", lambda args, label: verifies.append(label))

    def run(canary=False, yes=False, bin=None, probe=None):
        args = argparse.Namespace(fqbn=lb_flash.DEFAULT_FQBN, target="py32f030x8", probe=probe,
                                  frequency=500_000, canary=canary, yes=yes, bin=bin)
        return lb_flash.cmd_flash(args)
    run.verifies, run.calls, run.tree = verifies, fakebin, tree
    return run


def pyocd_calls(flasher, sub):
    return [c for c in flasher.calls() if c[0] == "pyocd" and c[1] == sub]


def test_canary_flash_then_sealed_flash_of_same_build(flasher):
    flasher(canary=True)
    (flash,) = pyocd_calls(flasher, "flash")
    assert flash[flash.index("--base-address") + 1] == "0x08000000"
    assert flash[flash.index("-t") + 1] == "py32f030x8"
    assert pyocd_calls(flasher, "reset")
    assert flasher.verifies == ["boot guard", "after guard", "after 30 s"]

    record = json.loads((flasher.tree / ".lb_canary.json").read_text())
    (digest,) = record
    assert record[digest]["bin"] == "lightning_bugs.ino.bin"

    flasher(yes=True)                                   # same bytes: now allowed on a sealed unit
    assert len(pyocd_calls(flasher, "flash")) == 2


def test_sealed_flash_of_different_build_is_refused(flasher, monkeypatch):
    flasher(canary=True)
    monkeypatch.setenv("FAKE_BIN_HEX", "ffeeddcc")      # a new build
    with pytest.raises(lb_flash.Fail, match="has not passed on a canary"):
        flasher(yes=True)
    assert len(pyocd_calls(flasher, "flash")) == 1


def test_sealed_flash_prompts_and_aborts_unless_confirmed(flasher, monkeypatch):
    flasher(canary=True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    with pytest.raises(lb_flash.Fail, match="aborted"):
        flasher()
    assert len(pyocd_calls(flasher, "flash")) == 1
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    flasher()
    assert len(pyocd_calls(flasher, "flash")) == 2


def test_probe_id_is_passed_to_pyocd(flasher):
    flasher(canary=True, probe="ABC123")
    (flash,) = pyocd_calls(flasher, "flash")
    assert flash[flash.index("-u") + 1] == "ABC123"


def test_failed_pyocd_flash_does_not_record_canary(flasher, monkeypatch):
    monkeypatch.setenv("FAKE_PYOCD_FAIL", "1")
    with pytest.raises(lb_flash.Fail, match="pyocd flash failed"):
        flasher(canary=True)
    assert not (flasher.tree / ".lb_canary.json").exists()
    assert flasher.verifies == []


def test_lost_swd_after_flash_does_not_record_canary(flasher, monkeypatch):
    def boom(args, label):
        raise RuntimeError("no probe")
    monkeypatch.setattr(lb_flash, "verify_connect", boom)
    clock = iter(range(0, 1000, 3))                     # make verify_retry's 5 s deadline pass fast
    monkeypatch.setattr(lb_flash.time, "monotonic", lambda: next(clock))
    with pytest.raises(lb_flash.Fail, match="could not reconnect over SWD"):
        flasher(canary=True)
    assert not (flasher.tree / ".lb_canary.json").exists()


def test_flash_existing_bin_is_checked_first(flasher, tmp_path):
    bad = tmp_path / "evil.bin"
    bad.write_bytes(b"\x00" + lb_flash.UNLOCK_KEYS["OPT_KEY1   0x08192A3B"])
    with pytest.raises(lb_flash.Fail, match="binary safety check failed"):
        flasher(canary=True, bin=str(bad))
    assert not pyocd_calls(flasher, "flash")

    good = tmp_path / "good.bin"
    good.write_bytes(b"\x01\x02\x03\x04")
    flasher(canary=True, bin=str(good))
    assert len(pyocd_calls(flasher, "flash")) == 1
    assert not any(c[0] == "arduino-cli" for c in flasher.calls()), "--bin must skip the build"
