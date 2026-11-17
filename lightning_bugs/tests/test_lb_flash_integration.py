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


# ─── dump (in-process, SWD reads stubbed) ────────────────────────────────────
@pytest.fixture
def dumper(tmp_path, monkeypatch):
    monkeypatch.setattr(lb_flash, "DUMP_DIR", tmp_path / "backups")
    image = bytes(range(256)) * 4
    reads = []

    def fake_read(args, size):
        reads.append(size)
        return reads_data[len(reads) - 1] if reads_data else image[:size]
    reads_data = []
    monkeypatch.setattr(lb_flash, "read_flash", fake_read)

    def run(output=None, size=1024, passes=2, poll=False):
        args = argparse.Namespace(probe=None, frequency=500_000, target="py32f030x8", output=output, size=size,
                                  passes=passes, poll=poll, poll_timeout=5.0)
        return lb_flash.cmd_dump(args)
    run.image, run.reads, run.queue, run.dir = image, reads, reads_data, tmp_path / "backups"
    return run


def test_dump_reads_twice_and_saves_identical_bytes(dumper):
    out = dumper()
    assert dumper.reads == [1024, 1024]
    assert out.read_bytes() == dumper.image and out.parent == dumper.dir
    assert out.name.startswith("dump_") and out.suffix == ".bin"


def test_dump_refuses_when_reads_differ(dumper):
    dumper.queue += [b"\x01\x02" * 8, b"\x01\x03" * 8]
    with pytest.raises(lb_flash.Fail, match="differ"):
        dumper()
    assert not dumper.dir.exists() or not list(dumper.dir.iterdir())


@pytest.mark.parametrize("fill", [0x00, 0xFF])
def test_dump_refuses_blank_or_protected_flash(dumper, fill):
    dumper.queue += [bytes([fill]) * 1024] * 2
    with pytest.raises(lb_flash.Fail, match="NOT a usable backup"):
        dumper()
    assert not dumper.dir.exists() or not list(dumper.dir.iterdir())


def test_dump_never_overwrites_a_backup(dumper, tmp_path):
    target = tmp_path / "mine.bin"
    target.write_bytes(b"precious")
    with pytest.raises(lb_flash.Fail, match="already exists"):
        dumper(output=str(target))
    assert target.read_bytes() == b"precious"


def test_read_flash_attaches_without_halt_and_reads_in_chunks(monkeypatch):
    import lb_sync
    calls = []

    class Target:
        def read_memory_block8(self, addr, n):
            calls.append((addr, n))
            return [1] * n

    class Session:
        board = type("B", (), {"target": Target()})()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: Session())
    args = argparse.Namespace(probe="X", frequency=1, target="t")
    data = lb_flash.read_flash(args, 2500)
    assert len(data) == 2500
    assert calls == [(0x08000000, 1024), (0x08000400, 1024), (0x08000800, 452)]


def test_read_flash_reports_swd_failure_as_fail(monkeypatch):
    import lb_sync

    def boom(ns):
        raise lb_sync.SyncError("no debug probe found")
    monkeypatch.setattr(lb_sync, "open_session", boom)
    with pytest.raises(lb_flash.Fail, match="could not read flash"):
        lb_flash.read_flash(argparse.Namespace(probe=None, frequency=1, target="t"), 16)


def test_cli_dump_is_a_subcommand(tree):
    r = cli(tree, "dump", "--help")
    assert r.returncode == 0 and "--output" in r.stdout and "--size" in r.stdout


def test_dump_single_pass_reads_once_and_marks_the_file_unverified(dumper):
    out = dumper(passes=1)
    assert dumper.reads == [1024]
    assert out.read_bytes() == dumper.image and out.stem.endswith("_unverified")


def test_dump_single_pass_still_refuses_blank_flash(dumper):
    dumper.queue += [b"\xff" * 1024]
    with pytest.raises(lb_flash.Fail, match="NOT a usable backup"):
        dumper(passes=1)


def test_dump_three_passes_compares_all(dumper):
    good = bytes(range(256)) * 4
    dumper.queue += [good, good, good[:-1] + b"\x00"]
    with pytest.raises(lb_flash.Fail, match="differ"):
        dumper(passes=3)
    assert dumper.reads == [1024] * 3


def test_dump_rejects_zero_passes(dumper):
    with pytest.raises(lb_flash.Fail, match="at least 1"):
        dumper(passes=0)
    assert dumper.reads == []


# ─── dump --poll ─────────────────────────────────────────────────────────────
@pytest.fixture
def poller(dumper, monkeypatch):
    """dumper plus a scripted read_flash_passes: each queued item is an Exception to raise or a list of images."""
    script, calls = [], []

    def fake(args, size, passes=1):
        calls.append(passes)
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    monkeypatch.setattr(lb_flash, "read_flash_passes", fake)
    monkeypatch.setattr(lb_flash.time, "sleep", lambda s: None)
    dumper.script, dumper.calls = script, calls
    return dumper


def test_poll_retries_until_the_chip_answers_then_saves(poller):
    img = poller.image[:1024]
    poller.script += [lb_flash.Fail("no answer")] * 3 + [[img, img]]
    out = poller(poll=True)
    assert out.read_bytes() == img
    assert poller.calls == [2, 2, 2, 2], "every attempt asks for all passes in one session"


def test_poll_gives_up_after_the_timeout(poller, monkeypatch):
    clock = iter(x * 2.0 for x in range(100))
    monkeypatch.setattr(lb_flash.time, "monotonic", lambda: next(clock))
    poller.script += [lb_flash.Fail("Target not detected")] * 50
    with pytest.raises(lb_flash.Fail, match=r"no usable read in 5 s .*Target not detected"):
        poller(poll=True)
    assert not poller.dir.exists() or not list(poller.dir.iterdir())


def test_poll_does_not_retry_a_fatal_error(poller):
    poller.script += [lb_flash.Fatal("no debug probe found"), [b"x" * 1024] * 2]
    with pytest.raises(lb_flash.Fatal, match="no debug probe"):
        poller(poll=True)
    assert poller.calls == [2]


def test_poll_still_checks_the_reads_agree_and_are_not_blank(poller):
    poller.script += [[b"\x01" * 1024, b"\x02" * 1024]]
    with pytest.raises(lb_flash.Fail, match="differ"):
        poller(poll=True)
    poller.script += [[b"\xff" * 1024] * 2]
    with pytest.raises(lb_flash.Fail, match="NOT a usable backup"):
        poller(poll=True)


def test_poll_single_pass_is_marked_unverified(poller):
    poller.script += [[poller.image[:1024]]]
    out = poller(poll=True, passes=1)
    assert out.stem.endswith("_unverified") and poller.calls == [1]


def test_poll_restores_the_pyocd_log_level_and_reports_ctrl_c(poller):
    import logging
    before = logging.getLogger("pyocd").level
    poller.script += [KeyboardInterrupt()]
    with pytest.raises(lb_flash.Fail, match="interrupted after 1 attempts"):
        poller(poll=True)
    assert logging.getLogger("pyocd").level == before


def test_read_flash_passes_reads_every_pass_in_one_session(monkeypatch):
    import lb_sync
    opened, reads = [], []

    class Target:
        def read_memory_block8(self, addr, n):
            reads.append(addr)
            return [7] * n

    class Session:
        board = type("B", (), {"target": Target()})()
        def __enter__(self): opened.append(1); return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: Session())
    images = lb_flash.read_flash_passes(argparse.Namespace(probe=None, frequency=1, target="t"), 2048, 3)
    assert len(images) == 3 and all(len(i) == 2048 for i in images) and len(opened) == 1
    assert len(reads) == 6


def test_cli_dump_offers_poll(tree):
    r = cli(tree, "dump", "--help")
    assert "--poll" in r.stdout and "--poll-timeout" in r.stdout
