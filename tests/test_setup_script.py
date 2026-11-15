"""lightning_bugs/tools/setup.sh runs at every sandbox launch and installs into ~/.local/bin and
~/.arduino15, so it must refuse to run outside a claude_sandbox container (guard on /etc/claude-sandbox)
unless the caller passes --i-know-this-modifies-my-system, in which case it must keep everything inside
the repo (lightning_bugs/.tools) and leave the user's home, arduino-cli and arduino config alone."""
import os
import re
import shutil
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.integration

OPT_IN = "--i-know-this-modifies-my-system"
GUARD = ('[ -f /etc/claude-sandbox ] || [ "${1:-}" = "--i-know-this-modifies-my-system" ] || '
         '{ echo "refusing: not inside a claude_sandbox container (to run it on your own machine, pass '
         '--i-know-this-modifies-my-system; see the header)" >&2; exit 1; }')
IN_SANDBOX = os.path.isfile("/etc/claude-sandbox")   # same test as the script's own `[ -f ... ]`


@pytest.fixture(scope="module")
def script(repo):
    return repo / "lightning_bugs" / "tools" / "setup.sh"


def code_lines(path):
    return [l for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_guard_is_first_command_before_any_side_effect(script):
    lines = code_lines(script)
    assert lines[0] == GUARD
    assert lines[1].startswith("set -euo pipefail")


def test_every_registered_setup_script_has_the_guard(repo):
    deps = yaml.safe_load((repo / "claude_sandbox_deps.yaml").read_text())
    for entry in deps.get("setup", []):
        assert code_lines(repo / entry["path"])[0] == GUARD, entry["path"]


def run_guard(tmp_path, marker_exists, *args):
    """Run the script's real guard line with /etc/claude-sandbox redirected to a temp path."""
    marker = tmp_path / "claude-sandbox"
    if marker_exists:
        marker.write_text("")
    line = GUARD.replace("/etc/claude-sandbox", str(marker))
    return subprocess.run(["bash", "-c", line + "; echo passed", "setup.sh", *args], capture_output=True, text=True)


def test_guard_refuses_without_marker(tmp_path):
    r = run_guard(tmp_path, marker_exists=False)
    assert r.returncode == 1 and "passed" not in r.stdout
    assert "refusing: not inside a claude_sandbox container" in r.stderr
    assert OPT_IN in r.stderr, "the refusal should say how to opt in"


def test_guard_allows_with_marker(tmp_path):
    r = run_guard(tmp_path, marker_exists=True)
    assert r.returncode == 0 and "passed" in r.stdout


def test_guard_allows_the_explicit_opt_in_without_marker(tmp_path):
    r = run_guard(tmp_path, False, OPT_IN)
    assert r.returncode == 0 and "passed" in r.stdout


@pytest.mark.parametrize("arg", ["--force", "-y", "--i-know", OPT_IN + "x", "yes", ""])
def test_guard_rejects_any_other_argument(tmp_path, arg):
    r = run_guard(tmp_path, False, arg)
    assert r.returncode == 1 and "passed" not in r.stdout


def test_opt_in_must_be_the_first_argument(tmp_path):
    assert run_guard(tmp_path, False, "x", OPT_IN).returncode == 1


@pytest.mark.skipif(IN_SANDBOX, reason="running inside a sandbox")
def test_real_script_refuses_outside_sandbox(script, tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "BIN_DIR": str(tmp_path / "bin")}
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "refusing" in r.stderr
    assert not (tmp_path / "bin").exists(), "script must not touch anything before the guard"


# --- running the real script against fake tools (no network, no installs) -------------------------------
FAKE_ARDUINO = """#!/bin/bash
echo "arduino-cli $* DATA=${ARDUINO_DIRECTORIES_DATA:-} USER=${ARDUINO_DIRECTORIES_USER:-} DL=${ARDUINO_DIRECTORIES_DOWNLOADS:-}" >> "$FAKE_LOG"
[ "$1" = version ] && echo "arduino-cli  Version: 0.33.0 Commit: abc Date: 2023-01-01"
exit 0
"""
FAKE_PIP_PYOCD = """#!/bin/bash
echo "$(basename "$0") $* PIP_CONSTRAINT=${PIP_CONSTRAINT:-}" >> "$FAKE_LOG"
exit 0
"""
FAKE_PYTHON = """#!/bin/bash
if [ "$1" = -m ] && [ "$2" = venv ]; then
  mkdir -p "$3/bin"
  for t in pip pyocd; do cp "$FAKE_TOOL" "$3/bin/$t"; chmod +x "$3/bin/$t"; done
  echo "python3 -m venv $3" >> "$FAKE_LOG"
fi
exit 0
"""


@pytest.fixture
def rig(repo, tmp_path):
    """A copy of tools/setup.sh + constraints.txt in a scratch tree, with fake arduino-cli/python3 on PATH."""
    tools = tmp_path / "lightning_bugs" / "tools"
    tools.mkdir(parents=True)
    shutil.copy(repo / "lightning_bugs" / "tools" / "setup.sh", tools)
    shutil.copy(repo / "lightning_bugs" / "constraints.txt", tools.parent)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name, body in (("arduino-cli", FAKE_ARDUINO), ("python3", FAKE_PYTHON), ("faketool", FAKE_PIP_PYOCD)):
        (fake / name).write_text(body)
        (fake / name).chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "calls.log"
    env = {**os.environ, "HOME": str(home), "PATH": f"{fake}:{os.environ['PATH']}", "FAKE_LOG": str(log),
           "FAKE_TOOL": str(fake / "faketool")}
    for var in ("BIN_DIR", "ARDUINO_DIRECTORIES_DATA", "ARDUINO_DIRECTORIES_USER", "PIP_CONSTRAINT"):
        env.pop(var, None)

    def run(*args):
        r = subprocess.run(["bash", str(tools / "setup.sh"), *args], capture_output=True, text=True, env=env)
        calls = log.read_text().splitlines() if log.exists() else []
        return r, calls
    run.root, run.home = tmp_path / "lightning_bugs", home
    return run


@pytest.mark.skipif(IN_SANDBOX, reason="host mode needs /etc/claude-sandbox absent")
def test_opt_in_run_stays_inside_the_repo(rig):
    r, calls = rig(OPT_IN)
    assert r.returncode == 0, r.stderr
    assert list(rig.home.iterdir()) == [], "must not create ~/.local, ~/.arduino15, ~/Arduino or anything else in HOME"
    assert (rig.root / ".tools" / "bin").is_dir()
    arduino = [c for c in calls if c.startswith("arduino-cli")]
    assert not any(" config " in f" {c} " for c in arduino), "must not touch arduino-cli's config on a real machine"
    tools = rig.root / ".tools"
    want = f"DATA={tools / 'arduino15'} USER={tools / 'arduino-user'} DL={tools / 'arduino-downloads'}"
    assert arduino and all(want in c for c in arduino), "data, sketchbook AND download-staging dirs must all be inside the repo"
    assert any(c.startswith("pip install -q -e") and "constraints.txt" in c for c in calls), "pins must apply"
    assert "ARDUINO_DIRECTORIES_DATA" in r.stdout, "should tell the user which variables to export"


@pytest.mark.skipif(not IN_SANDBOX, reason="sandbox mode needs /etc/claude-sandbox present")
def test_sandbox_run_uses_the_user_dirs_and_initialises_arduino_config(rig):
    r, calls = rig()
    assert r.returncode == 0, r.stderr
    assert (rig.home / ".local" / "bin").is_dir()
    assert not (rig.root / ".tools").exists()
    assert any(c.startswith("arduino-cli config init --overwrite") for c in calls)
    assert all("DATA= USER= DL=" in c for c in calls if c.startswith("arduino-cli"))


def test_pins_are_applied_on_every_run_in_either_mode(rig):
    r, calls = rig(*([] if IN_SANDBOX else [OPT_IN]))
    assert r.returncode == 0, r.stderr
    installs = [c for c in calls if c.startswith("pip install")]
    assert installs and all("constraints.txt" in c for c in installs if "--upgrade pip" not in c)


def test_script_syntax_ok(script):
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean(script):
    r = subprocess.run(["shellcheck", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_pinned_versions_are_declared(script):
    text = script.read_text()
    assert re.search(r"^ARDUINO_CLI_VERSION=\d+\.\d+\.\d+", text, re.M)
    assert re.search(r"^CORE=PY32Duino:PY32@\d+\.\d+\.\d+", text, re.M)
