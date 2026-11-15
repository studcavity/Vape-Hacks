"""Fixtures for driving tools/lb_flash.py against fake `arduino-cli` and `pyocd` executables."""
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

LB = Path(__file__).resolve().parent.parent

FAKE_ARDUINO = '''#!{py}
import json, os, sys
from pathlib import Path
log = Path(os.environ["FAKE_LOG"])
with log.open("a") as f:
    f.write(json.dumps(["arduino-cli", *sys.argv[1:]]) + "\\n")
if os.environ.get("FAKE_BUILD_FAIL"):
    sys.exit(1)
out = Path(sys.argv[sys.argv.index("--output-dir") + 1])
out.mkdir(parents=True, exist_ok=True)
if not os.environ.get("FAKE_NO_BIN"):
    (out / "lightning_bugs.ino.bin").write_bytes(bytes.fromhex(os.environ.get("FAKE_BIN_HEX", "00010203")))
(out / "lightning_bugs.ino.elf").write_bytes(b"\\x7fELF")
'''

FAKE_PYOCD = '''#!{py}
import json, os, sys
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a") as f:
    f.write(json.dumps(["pyocd", *sys.argv[1:]]) + "\\n")
sys.exit(1 if os.environ.get("FAKE_PYOCD_FAIL") and sys.argv[1] == "flash" else 0)
'''


@pytest.fixture
def fakebin(tmp_path, monkeypatch):
    """A dir on PATH with fake arduino-cli and pyocd; returns the list of recorded invocations."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    for name, body in (("arduino-cli", FAKE_ARDUINO), ("pyocd", FAKE_PYOCD)):
        p = bindir / name
        p.write_text(body.format(py=sys.executable))
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))

    def calls():
        import json
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return calls


@pytest.fixture
def tree(tmp_path):
    """A scratch copy of lightning_bugs/ (so lb_flash's ROOT, build/ and .lb_canary.json are isolated)."""
    dst = tmp_path / "lb"
    shutil.copytree(LB, dst, ignore=shutil.ignore_patterns(".venv", "build", "__pycache__", "tests"))
    return dst
