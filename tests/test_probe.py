"""The shared tools stay probe-agnostic, and the Pico probe's one install path (pyocd) stays pinned."""
import re

import pytest


def read(repo, rel):
    return (repo / rel).read_text()


@pytest.mark.parametrize("rel", ["lightning_bugs/tools/lb_flash.py", "lightning_bugs/host/lb_sync.py"])
def test_shared_tools_stay_probe_agnostic(repo, rel):
    text = read(repo, rel)
    for bad in (r"ft232", r"picoprobe", r"2e8a", r"0403", r"pyftdi", r"cmsis.?dap"):
        assert not re.search(bad, text, re.I), f"{rel} mentions {bad!r}: the probe is chosen with --probe"


def test_ftdi_plugin_is_gone(repo):
    assert not (repo / "lightning_bugs/probes").exists()
    for rel in ("lightning_bugs/tools/setup.sh", "requirements-dev.txt", "lightning_bugs/constraints.txt"):
        assert not re.search(r"ft232|pyftdi", read(repo, rel), re.I), rel


def test_pyocd_is_the_only_pin_and_is_exact(repo):
    pins = {}
    for line in read(repo, "lightning_bugs/constraints.txt").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, ver = line.partition("==")
            assert ver, f"{line!r} is not an exact == pin"
            pins[name.strip().lower()] = ver.strip()
    assert set(pins) == {"pyocd"}
    assert "-c lightning_bugs/constraints.txt" in read(repo, "requirements-dev.txt")
    assert 'PIP_CONSTRAINT="$ROOT/constraints.txt"' in read(repo, "lightning_bugs/tools/setup.sh")
