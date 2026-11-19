"""Drives firmware/lightning_bugs/lb_switch.h natively (plain C, no hardware access). Needs a C compiler."""
import pathlib
import shutil
import subprocess

import pytest

FW = pathlib.Path(__file__).resolve().parents[1] / "firmware" / "lightning_bugs"
CC = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler")


def test_off_pole_is_adc_below_20_only(tmp_path):
    src = tmp_path / "t.c"
    src.write_text('#include "lb_switch.h"\nint main(void) { return lbSwitchIsOff(0) && lbSwitchIsOff(19) '
                   '&& !lbSwitchIsOff(20) && !lbSwitchIsOff(1500) && !lbSwitchIsOff(4095) ? 0 : 1; }\n')
    subprocess.run([CC, "-std=c11", "-Wall", "-Werror", "-I", str(FW), str(src), "-o", str(tmp_path / "t")], check=True)
    assert subprocess.run([str(tmp_path / "t")]).returncode == 0


def test_header_is_valid_cpp_too(tmp_path):
    """The sketch compiles it as C++; make sure plain-C-isms did not slip in."""
    cxx = shutil.which("g++")
    if cxx is None:
        pytest.skip("no C++ compiler")
    src = tmp_path / "t.cpp"
    src.write_text('#include "lb_switch.h"\nint main() { return lbSwitchIsOff(5) && !lbSwitchIsOff(500) ? 0 : 1; }\n')
    subprocess.run([cxx, "-std=c++11", "-Wall", "-Werror", "-I", str(FW), str(src), "-o", str(tmp_path / "t")],
                   check=True)
    assert subprocess.run([str(tmp_path / "t")]).returncode == 0
