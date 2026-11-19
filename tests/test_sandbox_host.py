"""claude_sandbox_host.yaml: what this repo asks the host to attach to a sandbox. The launcher
(claude_sandbox, sandbox_host.py) parses it with a strict schema and attaches nothing until the host
user approves. These tests mirror that schema, and keep the Pico debug probe requested
(CLAUDE.md, "Debug probe")."""
import re

import pytest
import yaml

HEX4 = re.compile(r"^[0-9a-fA-F]{4}$")
NAME = re.compile(r"^[A-Za-z0-9._+-]+$")
DESCRIPTION = re.compile(r"^[A-Za-z0-9 .,()_/+:'-]{1,200}$")   # no markup: it lands in a prompt and CLAUDE.md
REQUIRED = {"name", "vendor_id", "product_id", "description"}
OPTIONAL = {"tools"}
MAX_USB, MAX_TOOLS, MAX_BYTES = 8, 8, 64 * 1024

PICO = ("2e8a", "000c")     # Raspberry Pi Pico running debug-probe (CMSIS-DAP) firmware


@pytest.fixture(scope="module")
def doc(repo):
    path = repo / "claude_sandbox_host.yaml"
    assert path.stat().st_size <= MAX_BYTES
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def usb(doc):
    return doc["usb"]


def test_only_known_keys(doc):
    assert set(doc) == {"usb", "files"}


# `files:` = sha256-pinned host files placed under the sandbox user's home (deps-file docs, "Pinned files").
FILE_KEYS = {"name", "host_path", "dest", "sha256", "on_error"}


def test_files_entries_are_pinned_optional_and_consistent(doc):
    files = doc["files"]
    assert files and len({f["name"] for f in files}) == len(files)
    for f in files:
        assert set(f) == FILE_KEYS and NAME.match(f["name"])
        assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"])
        assert f["on_error"] == "skip", "a missing pre-download must never stop a launch"
        assert f["host_path"].startswith("~/software/") and f["dest"] == f["host_path"]
        assert ".." not in f["dest"]


def test_files_hashes_match_the_pins_in_setup_sh(doc, repo):
    """setup.sh re-verifies every pre-downloaded file against its own table; the two must agree."""
    text = (repo / "lightning_bugs" / "tools" / "setup.sh").read_text()
    pins = dict(re.findall(r"^\s+\[([^\]]+)\]=([0-9a-f]{64})$", text, re.M))
    assert pins
    got = {f["dest"].rsplit("/", 1)[1]: f["sha256"] for f in doc["files"]}
    assert got == pins


def test_entries_follow_the_launcher_schema(usb):
    assert 1 <= len(usb) <= MAX_USB
    for e in usb:
        assert REQUIRED <= set(e) <= REQUIRED | OPTIONAL
        assert NAME.match(e["name"])
        # quoted in the file: an unquoted 0403 would be read by YAML as a number
        assert isinstance(e["vendor_id"], str) and HEX4.match(e["vendor_id"])
        assert isinstance(e["product_id"], str) and HEX4.match(e["product_id"])
        assert DESCRIPTION.match(e["description"]), "description must be plain text (no backticks, #, <, ;)"
        tools = e.get("tools", [])
        assert isinstance(tools, list) and len(tools) <= MAX_TOOLS
        assert all(isinstance(t, str) and NAME.match(t) for t in tools)


def test_names_and_ids_are_unique(usb):
    assert len({e["name"] for e in usb}) == len(usb)
    assert len({(e["vendor_id"].lower(), e["product_id"].lower()) for e in usb}) == len(usb)


def test_pico_probe_is_requested(usb):
    ids = {(e["vendor_id"].lower(), e["product_id"].lower()) for e in usb}
    assert PICO in ids, "Pico debug probe (2e8a:000c) missing"


def test_requested_id_is_documented(repo):
    assert "2e8a:000c" in (repo / "CLAUDE.md").read_text()
