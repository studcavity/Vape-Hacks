"""claude_sandbox_deps.yaml is parsed by the launcher with a strict schema (unknown keys abort
the launch) and runs as root / with the deploy key, so keep it valid and minimal. This mirrors
the rules documented in the sandbox instructions."""
import re

import pytest
import yaml

ALLOWED_KEYS = {"apt", "scripts", "binaries", "setup", "last_generated", "platform", "usb"}
NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")


@pytest.fixture(scope="module")
def deps(repo):
    return yaml.safe_load((repo / "claude_sandbox_deps.yaml").read_text())


def test_only_known_top_level_keys(deps):
    assert set(deps) <= ALLOWED_KEYS


def test_apt_entries_are_plain_package_names(deps):
    for pkg in deps.get("apt", []):
        assert re.match(r"^[a-z0-9][a-z0-9.+-]*(=[\w.+:~-]+)?$", pkg), pkg
    assert len(set(deps.get("apt", []))) == len(deps.get("apt", [])), "duplicate apt package"


@pytest.mark.parametrize("pkg", ["python3-venv", "libusb-1.0-0", "usbutils", "shellcheck"])
def test_expected_packages_present(deps, pkg):
    assert pkg in deps["apt"]


def test_remote_downloads_are_https_and_binaries_are_checksummed(deps):
    for entry in deps.get("scripts", []) + deps.get("binaries", []):
        assert NAME_RE.match(entry["name"])
        assert entry["url"].startswith("https://") and "@" not in entry["url"].split("/")[2]
    for entry in deps.get("binaries", []):
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), "binaries need a sha256"


def test_setup_entries(deps, repo):
    names = set()
    for entry in deps.get("setup", []):
        assert NAME_RE.match(entry["name"]) and entry["name"] not in names
        names.add(entry["name"])
        path = entry["path"]
        assert not path.startswith("/") and ".." not in path.split("/")
        assert (repo / path).is_file(), f"setup script {path} missing"
        assert 1 <= entry.get("timeout", 1800) <= 3600
        assert set(entry) <= {"name", "path", "args", "env", "timeout"}


def test_toolchain_setup_is_registered(deps):
    assert any(e["path"] == "lightning_bugs/tools/setup.sh" for e in deps.get("setup", []))


def test_metadata_is_present_and_well_formed(deps):
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", deps["last_generated"])
    assert "Ubuntu" in deps["platform"]


def test_no_usb_request_until_launcher_supports_it(deps):
    """An old launcher rejects unknown keys and aborts the whole launch (see USB plan on the
    throwaway/usb-passthrough-plan branch). Remove this test when the launcher supports `usb:`."""
    assert "usb" not in deps
