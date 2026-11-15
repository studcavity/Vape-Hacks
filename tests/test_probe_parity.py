"""Guards for the "two probe stacks, keep parity" rule (CLAUDE.md, "Probe parity").

These cannot prove parity, but they catch the usual ways it erodes: the rule being deleted, a probe-specific
detail leaking into the shared tools, or one stack being installed/documented without the other."""
import re

import pytest

STACK_A = ("Pico", "2e8a:000c")
STACK_B = ("FT232R", "0403:6001", "ft232r:")


def read(repo, rel):
    return (repo / rel).read_text()


@pytest.mark.parametrize("rel", ["CLAUDE.md", "lightning_bugs/README.md", "lightning_bugs/probes/ft232r/README.md"])
def test_both_stacks_are_documented_with_the_parity_rule(repo, rel):
    text = read(repo, rel)
    assert re.search(r"parity", text, re.I), f"{rel} lost the probe-parity note"
    for needle in STACK_A + STACK_B:
        assert needle in text, f"{rel} does not mention {needle!r}"


def test_claude_md_rule_tells_agents_to_implement_on_both(repo):
    text = read(repo, "CLAUDE.md")
    section = text[text.index("## Probe parity"):]
    section = section[:section.index("\n## ", 5)]
    assert "both are considered supported" in section
    assert "Always implement changes for both" in section


@pytest.mark.parametrize("rel", ["lightning_bugs/tools/lb_flash.py", "lightning_bugs/host/lb_sync.py"])
def test_shared_tools_stay_probe_agnostic(repo, rel):
    text = read(repo, rel)
    for bad in (r"ft232", r"picoprobe", r"2e8a", r"0403", r"pyftdi", r"cmsis.?dap"):
        assert not re.search(bad, text, re.I), f"{rel} mentions {bad!r}: put probe-specific code in the probe's package"


def test_setup_script_installs_both_stacks(repo):
    text = read(repo, "lightning_bugs/tools/setup.sh")
    assert "pip\" install -q --upgrade pip pyocd" in text          # stack A needs only pyocd
    assert 'install -q -e "$ROOT/probes/ft232r"' in text           # stack B


def test_dev_requirements_install_the_plugin(repo):
    assert "-e lightning_bugs/probes/ft232r" in read(repo, "requirements-dev.txt")


def test_libusb_is_available_to_both_stacks(repo):
    """pyocd (stack A) and pyftdi (stack B) both reach the adaptor through libusb."""
    import yaml
    deps = yaml.safe_load(read(repo, "claude_sandbox_deps.yaml"))
    assert "libusb-1.0-0" in deps["apt"]


def test_plugin_has_its_own_tests(repo):
    tests = list((repo / "lightning_bugs/tests/ft232r").glob("test_*.py"))
    assert len(tests) >= 5
