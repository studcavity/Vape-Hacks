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


@pytest.fixture(scope="module")
def switch_exe(tmp_path_factory):
    d = tmp_path_factory.mktemp("switch")
    exe = d / "switch"
    subprocess.run([CXX, "-std=c++17", "-Wall", "-Wno-unused-function", "-I", str(LB / "tests" / "fake_arduino"),
                    "-I", str(LB / "firmware" / "lightning_bugs"), str(LB / "tests" / "fake_arduino" / "switch_driver.cpp"),
                    "-o", str(exe)], check=True)

    def run(*args):
        out = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stdout + out.stderr
        return dict(kv.split("=") for kv in out.stdout.split() if "=" in kv)
    return run


def test_switch_at_off_pole_sleeps_in_stop_until_it_moves(switch_exe):
    r = switch_exe("off")
    assert int(r["stop_wfis"]) >= 20000, "should have slept until the simulated switch move"
    assert r["released"] == "1" and r["off_after"] == "0"
    assert r["synced"] == "0" and r["wakes"] == "1", "STOP stops millis(): the unit must be unsynced after waking"
    assert r["led_power_pin"] == "1", "LED driver power (PA15, HIGH = off) must be cut while asleep"


def test_switch_not_at_off_pole_does_not_enter_stop(switch_exe):
    r = switch_exe()
    assert r["stop_wfis"] == "0" and r["released"] == "0"



def test_switch_at_vdda_does_not_make_the_loop_re_read_the_switch_every_pass(switch_exe):
    """Measured on the canary: at VDDA each analog->digital flip raises two edges by itself. They must not count as
    switch moves, or every loop pass would re-read PA2 and abandon its wait."""
    r = switch_exe("vdda")
    assert r["pa2_reads"] == "1", f"one read at boot, none after; got {r['pa2_reads']}"
    assert r["stop_wfis"] == "0"
