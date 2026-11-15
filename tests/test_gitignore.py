"""The repo-root .gitignore must keep generated firmware out and device dumps trackable
(CLAUDE.md: "Compiled binaries: don't commit them by default")."""
import subprocess

import pytest

pytestmark = pytest.mark.integration


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def ignored(repo, path):
    return git(repo, "check-ignore", "-q", "--no-index", path).returncode == 0


@pytest.mark.parametrize("path", [
    "lightning_bugs/build/lightning_bugs.ino.bin",
    "build/x.o",
    "sketch.ino.elf",
    "sketch.ino.hex",
    "sketch.ino.map",
    "firmware.bin",
    "lightning_bugs/.lb_canary.json",
    "lightning_bugs/.venv/bin/pyocd",
    "lightning_bugs/host/__pycache__/lb_sync.cpython-312.pyc",
    ".arduino15/package_index.json",
])
def test_generated_files_are_ignored(repo, path):
    assert ignored(repo, path), f"{path} should be git-ignored"


@pytest.mark.parametrize("path", [
    "backup_flash.bin",
    "backup_flash_pulse_x.bin",
    "lightning_bugs/firmware/lightning_bugs/lightning_bugs.ino",
    "lightning_bugs/tools/lb_flash.py",
    "claude_sandbox_deps.yaml",
])
def test_sources_and_device_dumps_are_not_ignored(repo, path):
    assert not ignored(repo, path), f"{path} must stay trackable"


def test_no_tracked_file_matches_an_ignore_rule(repo):
    out = git(repo, "ls-files", "-ci", "--exclude-standard").stdout.split()
    # Device dumps are the documented exception and are not matched, so this is empty.
    assert out == [], f"tracked files that .gitignore says to ignore: {out}"


def test_no_compiled_firmware_is_tracked(repo):
    tracked = git(repo, "ls-files").stdout.splitlines()
    bad = [f for f in tracked if f.endswith((".elf", ".hex", ".map", ".o"))
           or (f.endswith(".bin") and "backup_flash" not in f)]
    assert bad == [], f"compiled outputs tracked: {bad}"
