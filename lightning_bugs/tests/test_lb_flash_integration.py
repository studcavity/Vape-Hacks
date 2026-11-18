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


def _flags(call):
    return call[call.index("--build-property") + 1]


def test_cli_build_defaults_to_the_first_model(tree, fakebin):
    import lb_catalog
    first = lb_catalog.MODELS[0]
    r = cli(tree, "build")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"-DLB_MODEL_ID={first.id}u" in _flags(fakebin()[0])
    assert f"model: {first.name} (id {first.id})" in r.stdout


def test_cli_build_passes_the_chosen_model_id(tree, fakebin):
    import lb_catalog
    extra = lb_catalog.Model(7, "pulsex-test", lb_catalog.MODELS[0].traits)
    path = tree / "host" / "lb_catalog.py"
    path.write_text(path.read_text().replace("    PULSEX,", f"    PULSEX,\n    PULSEX.derive(7, {extra.name!r}),", 1))
    r = cli(tree, "build", "--model", "pulsex-test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "-DLB_MODEL_ID=7u" in _flags(fakebin()[0])


def test_cli_build_rejects_unknown_model_and_lists_known_ones(tree, fakebin):
    r = cli(tree, "build", "--model", "bogus")
    assert r.returncode != 0 and "pulsex" in r.stderr and fakebin() == []


def test_cli_build_refuses_a_binary_reporting_the_wrong_model(tree, fakebin):
    import struct
    import lb_sync
    layout = lb_catalog_layout()
    w = [0] * layout.words
    w[0], w[1], w[2], w[3] = lb_sync.MAGIC0, lb_sync.MAGIC1, 4 << 16, layout.words
    w[layout.index["model_id"]] = 5                                   # firmware says model 5; we asked for 0
    r = cli(tree, "build", env={"FAKE_BIN_HEX": struct.pack("<%dI" % len(w), *w).hex()})
    assert r.returncode == 1 and "model id was not applied" in r.stdout


def lb_catalog_layout():
    import lb_catalog
    return lb_catalog.CATALOG.formats.layout(4, lb_catalog.CATALOG.formats.latest(4))


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

    def run(canary=False, yes=False, bin=None, probe=None, wait=0.0):
        args = argparse.Namespace(fqbn=lb_flash.DEFAULT_FQBN, target="py32f030x8", probe=probe,
                                  frequency=500_000, canary=canary, yes=yes, bin=bin, wait=wait)
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


# ─── watch ───────────────────────────────────────────────────────────────────
class FakeProbe:
    """Answers (with `dpidr`) only while its clock is inside one of `windows`; every read costs 1 ms."""
    def __init__(self, windows=(), dpidr=0x0BB11477, interrupt_at=None):
        self.t, self.windows, self.dpidr, self.interrupt_at = 0.0, windows, dpidr, interrupt_at

    def swj_sequence(self, n, bits):
        pass

    def read_dp(self, addr, now=True):
        self.t += 0.001
        if self.interrupt_at is not None and self.t >= self.interrupt_at:
            raise KeyboardInterrupt
        if any(a <= self.t < b for a, b in self.windows):
            return self.dpidr
        raise RuntimeError("No ACK")


def watch(probe, timeout=1.0):
    lines = []
    return lb_flash.run_watch(probe, timeout, clock=lambda: probe.t, report=lines.append), lines


def test_watch_reports_no_window_when_the_chip_never_answers():
    windows, lines = watch(FakeProbe())
    assert windows == [] and "0 window(s)" in lines[-1]


def test_watch_measures_one_windows_start_length_and_dpidr():
    windows, lines = watch(FakeProbe(windows=[(0.200, 0.350)]))
    (w,) = windows
    assert 140 <= w["ms"] <= 150 and w["dpidr"] == 0x0BB11477
    assert any("DPIDR 0x0BB11477" in l and "answered at +0.2" in l for l in lines)
    assert "1 window(s), longest" in lines[-1]


def test_watch_counts_two_windows_separately():
    windows, _ = watch(FakeProbe(windows=[(0.1, 0.2), (0.5, 0.52)]))
    assert len(windows) == 2 and windows[1]["ms"] < 25


def test_watch_ignores_a_floating_line_and_junk_idcodes():
    for junk in (0xFFFFFFFF, 0x00000000, 0x0BB11476):          # all ones; zero; bit 0 clear
        windows, _ = watch(FakeProbe(windows=[(0.0, 5.0)], dpidr=junk))
        assert windows == [], hex(junk)


def test_watch_closes_the_window_it_is_in_when_interrupted_or_timed_out():
    windows, lines = watch(FakeProbe(windows=[(0.2, 9.0)], interrupt_at=0.4))
    assert len(windows) == 1 and "interrupted" in lines
    windows, _ = watch(FakeProbe(windows=[(0.2, 9.0)]), timeout=0.5)
    assert len(windows) == 1


def test_watch_tolerates_a_short_dropout_inside_a_window():
    windows, _ = watch(FakeProbe(windows=[(0.100, 0.200), (0.203, 0.300)]))   # a 3 ms gap
    assert len(windows) == 1


def test_open_raw_probe_needs_a_probe(monkeypatch):
    from pyocd.core.helpers import ConnectHelper
    monkeypatch.setattr(ConnectHelper, "get_all_connected_probes", staticmethod(lambda blocking=False: []))
    args = argparse.Namespace(probe=None, frequency=500_000, target="py32f030x8")
    with pytest.raises(lb_flash.Fatal, match="no debug probe"):
        lb_flash.open_raw_probe(args)


def test_open_raw_probe_honours_the_probe_id(monkeypatch):
    from pyocd.core.helpers import ConnectHelper
    other = type("P", (), {"unique_id": "OTHER"})()
    monkeypatch.setattr(ConnectHelper, "get_all_connected_probes", staticmethod(lambda blocking=False: [other]))
    args = argparse.Namespace(probe="WANTED", frequency=500_000, target="py32f030x8")
    with pytest.raises(lb_flash.Fatal, match="no debug probe"):
        lb_flash.open_raw_probe(args)


def test_cli_watch_is_a_subcommand(tree):
    r = cli(tree, "watch", "--help")
    assert r.returncode == 0 and "--timeout" in r.stdout


def test_dump_accepts_timeout_as_an_alias_of_poll_timeout(tree):
    """`watch` calls it --timeout; dump used to accept only --poll-timeout and rejected --timeout."""
    r = cli(tree, "dump", "--poll", "--timeout", "1", "--help")
    assert r.returncode == 0 and "--timeout" in r.stdout


# ─── options (read-only) ─────────────────────────────────────────────────────
def word(lo16):
    """An option word as stored: setting in the low half, its one's complement in the high half."""
    return ((~lo16 & 0xFFFF) << 16) | lo16


def optr(rdp=0xAA, bor_en=0, bor_lev=0, iwdg_sw=1, wwdg_sw=1, nrst_gpio=0, nboot1=1):
    return rdp | bor_en << 8 | bor_lev << 9 | iwdg_sw << 12 | wwdg_sw << 13 | nrst_gpio << 14 | nboot1 << 15


class FakeOptionsTarget:
    def __init__(self, user=None, wrp=0xFFFF, dbg_cr=0, fz1=0, live=None, bad_user=False, dbgen=1):
        user = optr() if user is None else user
        self.mem = {lb_flash.OPTION_BASE: (word(user) ^ 1) if bad_user else word(user),
                    lb_flash.OPTION_BASE + 4: 0x1F1F0000 | 0, lb_flash.OPTION_BASE + 8: 0,
                    lb_flash.OPTION_BASE + 12: word(wrp),
                    lb_flash.FLASH_OPTR: user if live is None else live, lb_flash.FLASH_SDKR: 0, lb_flash.FLASH_WRPR: wrp,
                    lb_flash.RCC_APBENR1: dbgen << lb_flash.DBGEN_BIT,
                    lb_flash.DBG_IDCODE: 0, lb_flash.DBG_CR: dbg_cr, lb_flash.DBG_FZ1: fz1, lb_flash.DBG_FZ2: 0}
        self.reads = []

    def read32(self, addr):
        self.reads.append(addr)
        return self.mem[addr]

    def write32(self, *a):          # the command is read-only: any write is a bug
        raise AssertionError("options must not write")


def text(target):
    return "\n".join(lb_flash.format_options(lb_flash.read_options(target)))


def test_options_decodes_a_stock_unit():
    out = text(FakeOptionsTarget(user=optr(nrst_gpio=1, iwdg_sw=0, bor_en=1, bor_lev=6), dbg_cr=0))
    assert "RDP 0xAA: level 0, no read protection" in out
    assert "NRST: GPIO (no reset pin)" in out
    assert "IWDG: HARDWARE" in out and "WWDG: software" in out
    assert "BOR: on, rising/falling threshold 3.0/2.9 V" in out
    assert "DBG_STOP (CR bit 1) = 0: clear" in out
    assert "none (all 16 sectors unprotected)" in out


def test_options_shows_dbg_stop_set_and_the_freeze_bits():
    out = text(FakeOptionsTarget(dbg_cr=0b10, fz1=1 << 12))
    assert "DBG_STOP (CR bit 1) = 1: SET" in out
    assert "DBG_IWDG_STOP (FZ1 bit 12) = 1, DBG_WWDG_STOP (bit 11) = 0" in out


def test_options_flags_read_protection_and_a_bad_complement():
    assert "LEVEL 1" in text(FakeOptionsTarget(user=optr(rdp=0x00)))
    out = text(FakeOptionsTarget(bad_user=True))
    assert "COMPLEMENT MISMATCH" in out and "read protection ON" in out


def test_options_flags_a_pending_option_change():
    assert "DIFFERS from the option bytes" in text(FakeOptionsTarget(live=optr(nrst_gpio=1)))
    assert "matches the option bytes" in text(FakeOptionsTarget())


def test_options_reads_only_the_expected_addresses_and_never_writes():
    target = FakeOptionsTarget()
    lb_flash.read_options(target)
    assert sorted(target.reads) == sorted(target.mem)


def test_options_does_not_read_dbgmcu_when_the_debug_clock_is_off():
    target = FakeOptionsTarget(dbgen=0, dbg_cr=2)
    out = text(target)
    assert "DBGEN (bit 27) = 0" in out and "DBGMCU was NOT read" in out
    assert "DBG_STOP (CR bit 1)" not in out
    assert not {lb_flash.DBG_IDCODE, lb_flash.DBG_CR, lb_flash.DBG_FZ1, lb_flash.DBG_FZ2} & set(target.reads)


def test_options_asks_pyocd_not_to_run_the_pack_debug_start_sequence(monkeypatch):
    import lb_sync
    seen = []

    class Session:
        board = type("B", (), {"target": FakeOptionsTarget()})()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: seen.append(ns.extra_options) or Session())
    lb_flash.cmd_options(argparse.Namespace(probe=None, frequency=1, target="t", poll=False, timeout=1.0))
    assert seen == [{"pack.debug_sequences.disabled_sequences": "DebugCoreStart"}]


def test_dump_still_uses_the_pack_sequence(monkeypatch):
    """Only `options` opts out: dump keeps pyocd's normal connect behaviour."""
    import lb_sync
    seen = []

    class Target:
        def read_memory_block8(self, a, n): return [1] * n

    class Session:
        board = type("B", (), {"target": Target()})()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: seen.append(ns.extra_options) or Session())
    lb_flash.read_flash(argparse.Namespace(probe=None, frequency=1, target="t"), 16)
    assert seen == [None]


def test_options_register_addresses_match_the_reference_manual():
    assert (lb_flash.OPTION_BASE, lb_flash.FLASH_OPTR, lb_flash.DBG_CR) == (0x1FFF0E80, 0x40022020, 0x40015804)


def test_cmd_options_polls_and_prints(monkeypatch, capsys):
    import lb_sync
    target = FakeOptionsTarget(dbg_cr=2)
    tries = []

    class Session:
        board = type("B", (), {"target": target})()
        def __enter__(self):
            tries.append(1)
            if len(tries) < 3:
                raise RuntimeError("No ACK")
            return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: Session())
    monkeypatch.setattr(lb_flash.time, "sleep", lambda s: None)
    args = argparse.Namespace(probe=None, frequency=1, target="t", poll=True, timeout=5.0)
    lb_flash.cmd_options(args)
    out = capsys.readouterr().out
    assert "connected on attempt 3" in out and "DBG_STOP (CR bit 1) = 1: SET" in out


def test_cmd_options_without_poll_fails_fast(monkeypatch):
    import lb_sync
    monkeypatch.setattr(lb_sync, "open_session", lambda ns: (_ for _ in ()).throw(RuntimeError("No ACK")))
    with pytest.raises(lb_flash.Fail, match="could not read the option bytes"):
        lb_flash.cmd_options(argparse.Namespace(probe=None, frequency=1, target="t", poll=False, timeout=1.0))


def test_cli_options_is_a_subcommand(tree):
    r = cli(tree, "options", "--help")
    assert r.returncode == 0 and "--poll" in r.stdout


# ─── flash --wait ────────────────────────────────────────────────────────────
@pytest.fixture
def waiter(flasher, monkeypatch):
    """flasher plus a scripted with_target for the --wait poll: the script lists what each attempt does."""
    events, script = [], []

    def fake(args, fn, what="flash", extra_options=None):
        flashed = bool(pyocd_calls(flasher, "flash"))
        events.append(("poll", flashed))
        step = script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step
    monkeypatch.setattr(lb_flash, "with_target", fake)
    flasher.events, flasher.script = events, script
    return flasher


def test_flash_wait_polls_until_the_chip_answers_then_flashes_once(waiter):
    waiter.script += [lb_flash.Fail("No ACK")] * 3 + [0x20000A78]
    waiter(canary=True, wait=30.0)
    assert [e[0] for e in waiter.events] == ["poll"] * 4
    assert not any(flashed for _, flashed in waiter.events), "pyocd flash must not start before the chip answers"
    assert len(pyocd_calls(waiter, "flash")) == 1
    assert waiter.verifies == ["boot guard", "after guard", "after 30 s"]


def test_flash_wait_times_out_without_running_pyocd_or_recording_a_canary(waiter, monkeypatch):
    clock = iter(x * 20.0 for x in range(100))
    monkeypatch.setattr(lb_flash.time, "monotonic", lambda: next(clock))
    waiter.script += [lb_flash.Fail("No ACK")] * 50
    with pytest.raises(lb_flash.Fail, match="no usable read in 30 s"):
        waiter(canary=True, wait=30.0)
    assert not pyocd_calls(waiter, "flash")
    assert not (waiter.tree / ".lb_canary.json").exists()


def test_flash_wait_gives_up_at_once_with_no_probe(waiter):
    waiter.script += [lb_flash.Fatal("no debug probe found"), 1]
    with pytest.raises(lb_flash.Fatal, match="no debug probe"):
        waiter(canary=True, wait=30.0)
    assert len(waiter.events) == 1 and not pyocd_calls(waiter, "flash")


def test_flash_without_wait_does_not_poll(waiter):
    waiter(canary=True)
    assert waiter.events == [] and len(pyocd_calls(waiter, "flash")) == 1


def test_flash_wait_comes_after_the_sealed_unit_prompt(waiter, monkeypatch):
    waiter.script += [1, 1]
    waiter(canary=True, wait=5.0)                              # records the canary, uses one scripted step
    order = []
    monkeypatch.setattr("builtins.input", lambda prompt: order.append("prompt") or "y")
    orig = lb_flash.with_target
    monkeypatch.setattr(lb_flash, "with_target", lambda *a, **k: order.append("poll") or orig(*a, **k))
    waiter(wait=5.0)
    assert order == ["prompt", "poll"], "do not spend the connect window on a prompt"


def test_flash_wait_flag_in_the_cli(tree):
    r = cli(tree, "flash", "--help")
    assert r.returncode == 0 and "--wait" in r.stdout
