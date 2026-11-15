"""lightning_bugs/tools/setup.sh runs at every sandbox launch and installs into ~/.local/bin, so it
must refuse to run outside a claude_sandbox container (guard on /etc/claude-sandbox)."""
import os
import re
import shutil
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.integration

GUARD = '[ -f /etc/claude-sandbox ] || { echo "refusing: not inside a claude_sandbox container" >&2; exit 1; }'


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


def run_guard(tmp_path, marker_exists):
    """Run the script's real guard line with /etc/claude-sandbox redirected to a temp path."""
    marker = tmp_path / "claude-sandbox"
    if marker_exists:
        marker.write_text("")
    line = GUARD.replace("/etc/claude-sandbox", str(marker))
    return subprocess.run(["bash", "-c", line + "; echo passed"], capture_output=True, text=True)


def test_guard_refuses_without_marker(tmp_path):
    r = run_guard(tmp_path, marker_exists=False)
    assert r.returncode == 1 and "passed" not in r.stdout
    assert "refusing: not inside a claude_sandbox container" in r.stderr


def test_guard_allows_with_marker(tmp_path):
    r = run_guard(tmp_path, marker_exists=True)
    assert r.returncode == 0 and "passed" in r.stdout


@pytest.mark.skipif(os.path.exists("/etc/claude-sandbox"), reason="running inside a sandbox")
def test_real_script_refuses_outside_sandbox(script, tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "BIN_DIR": str(tmp_path / "bin")}
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "refusing" in r.stderr
    assert not (tmp_path / "bin").exists(), "script must not touch anything before the guard"


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
