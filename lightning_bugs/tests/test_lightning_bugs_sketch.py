"""Compiles the real lightning_bugs.ino natively against tests/fake_arduino/Arduino.h and runs its loop() under a
simulated clock. This tests the sketch's own control flow; whether the chip behaves as the fake assumes is not covered.
Needs g++; skipped without one."""
import pathlib
import shutil
import subprocess

import pytest

LB = pathlib.Path(__file__).resolve().parents[1]
CXX = shutil.which("g++")
pytestmark = pytest.mark.skipif(CXX is None, reason="no C++ compiler")


@pytest.fixture(scope="module")
def show_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("sketch")
    exe = d / "show"
    subprocess.run([CXX, "-std=c++17", "-Wall", "-Wno-unused-function", "-I", str(LB / "tests" / "fake_arduino"),
                    "-I", str(LB / "firmware" / "lightning_bugs"), str(LB / "tests" / "fake_arduino" / "show_driver.cpp"),
                    "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    return dict(line.split("=") for part in out.stdout.split("\n") for line in part.split() if "=" in line)


def test_resync_that_cuts_a_show_short_leaves_the_leds_unpowered_until_the_next_show(show_run):
    assert show_run["show_cut_short"] == "1"
    assert int(show_run["wait_samples"]) > 3_000_000, "should have waited most of an hour"
    assert show_run["powered_while_waiting"] == "0"
