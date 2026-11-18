"""Drives firmware/lightning_bugs/lb_power_policy.h natively (it is plain C with no hardware access).

These are the rules that decide when an unprotected cell gets put to sleep, so they are tested directly
rather than through the sketch. Needs a C compiler; skipped without one.
"""
import pathlib
import shutil
import subprocess
import textwrap

import pytest

FW = pathlib.Path(__file__).resolve().parents[1] / "firmware" / "lightning_bugs"
CC = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler")

DRIVER = r'''
#include <stdio.h>
#include "lb_power_policy.h"
static const char* name(LbPwrAction a) { return a == LB_PWR_RUN ? "RUN" : a == LB_PWR_WINDOW ? "WINDOW" : "SLEEP"; }
/* stdin: lines "feed mv usb now", "woke now", "act now" */
int main(void) {
    LbPower p; lbPowerInit(&p);
    char cmd[16]; unsigned a, b, c;
    while (scanf("%15s", cmd) == 1) {
        if (!strcmp(cmd, "feed")) { scanf("%u %u %u", &a, &b, &c); lbPowerFeed(&p, a, b, c); }
        else if (!strcmp(cmd, "woke")) { scanf("%u", &a); lbPowerWoke(&p, a); }
        else if (!strcmp(cmd, "act")) { scanf("%u", &a); printf("%s %d\n", name(lbPowerAction(&p, a)), p.latched); }
    }
    return 0;
}
'''


@pytest.fixture(scope="module")
def policy(tmp_path_factory):
    d = tmp_path_factory.mktemp("policy")
    (d / "drv.c").write_text("#include <string.h>\n" + DRIVER)
    exe = d / "drv"
    subprocess.run([CC, "-std=c11", "-Wall", "-Werror", "-I", str(FW), str(d / "drv.c"), "-o", str(exe)], check=True)

    def run(script: str) -> list[str]:
        out = subprocess.run([str(exe)], input=textwrap.dedent(script), capture_output=True, text=True, check=True)
        return out.stdout.split("\n")[:-1]
    return run


def test_header_is_valid_cpp_too(tmp_path):
    """The sketch compiles it as C++; make sure plain-C-isms did not slip in."""
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("no C++ compiler")
    src = tmp_path / "t.cpp"
    src.write_text('#include "lb_power_policy.h"\nint main() { LbPower p; lbPowerInit(&p); '
                   'return lbPowerAction(&p, 0) == LB_PWR_RUN ? 0 : 1; }\n')
    subprocess.run([cxx, "-std=c++11", "-Wall", "-Werror", "-I", str(FW), str(src), "-o", str(tmp_path / "t")],
                   check=True)
    assert subprocess.run([str(tmp_path / "t")]).returncode == 0


def test_healthy_battery_runs(policy):
    out = policy("feed 3900 0 1000\nfeed 3900 0 11000\nact 12000\n")
    assert out == ["RUN 0"]


def test_needs_three_consecutive_low_readings(policy):
    out = policy("""
        feed 3590 0 10000
        feed 3590 0 20000
        act 20000
        feed 3700 0 30000
        feed 3590 0 40000
        feed 3590 0 50000
        act 50000
        feed 3590 0 60000
        act 60000
    """)
    assert out == ["RUN 0", "RUN 0", "WINDOW 1"]


def test_window_then_sleep_then_wake_opens_new_window(policy):
    out = policy("""
        feed 3500 0 0
        feed 3500 0 10000
        feed 3500 0 20000
        act 20001
        act 79999
        act 80000
        woke 500000
        act 500001
        act 559999
        act 560000
    """)
    # latched at t=20000: window to 80000
    assert out == ["WINDOW 1", "WINDOW 1", "SLEEP 1", "WINDOW 1", "WINDOW 1", "SLEEP 1"]


def test_stays_latched_between_thresholds_and_clears_on_recovery(policy):
    out = policy("""
        feed 3500 0 0
        feed 3500 0 1
        feed 3500 0 2
        feed 3700 0 100000
        act 200000
        feed 3750 0 110000
        act 200000
    """)
    assert out == ["SLEEP 1", "RUN 0"]


def test_usb_with_healthy_supply_clears_the_latch(policy):
    out = policy("""
        feed 3500 0 0
        feed 3500 0 1
        feed 3500 0 2
        feed 3650 1 100000
        act 200000
    """)
    assert out == ["RUN 0"]


def test_usb_input_stuck_high_cannot_defeat_the_floor(policy):
    """If PF0's polarity were inverted, 'USB present' would read true on battery. The floor still latches."""
    out = policy("""
        feed 3390 1 0
        feed 3390 1 10000
        act 10000
        feed 3390 1 20000
        act 20000
        act 100000
    """)
    assert out == ["RUN 0", "WINDOW 1", "SLEEP 1"]


def test_usb_with_supply_just_above_floor_does_not_latch(policy):
    assert policy("feed 3450 1 0\nfeed 3450 1 1\nfeed 3450 1 2\nact 3\n") == ["RUN 0"]


def test_unreadable_battery_never_latches(policy):
    assert policy("feed 0 0 0\nfeed 0 0 1\nfeed 0 0 2\nfeed 0 0 3\nact 4\n") == ["RUN 0"]


def test_window_survives_millis_wraparound(policy):
    t = 0xFFFFFFFF - 10000
    out = policy(f"feed 3500 0 {t}\nfeed 3500 0 {t}\nfeed 3500 0 {t}\nact {t + 1}\nact {(t + 60001) % 2**32}\n")
    assert out == ["WINDOW 1", "SLEEP 1"]


def test_accidental_wakes_are_cheap():
    """The cost of one 60 s window at idle current, against the cell."""
    idle_ma, window_s, capacity_mah = 0.40, 60, 800
    per_wake_mah = idle_ma * window_s / 3600
    assert per_wake_mah == pytest.approx(0.00667, rel=0.01)
    assert 100 * per_wake_mah < 0.001 * capacity_mah       # a hundred accidental wakes < 0.1 % of the cell
