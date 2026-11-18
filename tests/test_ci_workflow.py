"""The CI workflow keeps the checks that cannot run anywhere else (they need the arduino toolchain)."""
from pathlib import Path

import yaml

WORKFLOW = yaml.safe_load((Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text())


def test_toolchain_job_builds_for_real_and_cannot_skip():
    job = WORKFLOW["jobs"]["toolchain"]
    assert job["env"]["LB_REQUIRE_TOOLCHAIN"] == "1"
    steps = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "setup.sh --i-know-this-modifies-my-system" in steps
    assert "lb_stack.py --all" in steps and "test_lb_stack.py" in steps
    assert "unit" in job["needs"]


def test_unit_job_still_excludes_toolchain_and_integration_tests():
    run = "\n".join(str(s.get("run", "")) for s in WORKFLOW["jobs"]["unit"]["steps"])
    assert '-m "not integration"' in run
