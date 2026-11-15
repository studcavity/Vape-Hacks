"""`python -m pyocd_ft232r`: list FT232R adaptors and run the wiring self-test (no target needed).

    python -m pyocd_ft232r                # list adaptors
    python -m pyocd_ft232r check [SERIAL] # loopback test: SWDIO_OUT -> R -> SWDIO <- SWDIO_IN
"""
from __future__ import annotations

import argparse
import os
import sys

from .probe import list_adaptors
from .transport import CalibrationError, FtdiTransport
from .wire import Pins


def main(argv=None, adaptors=None, transport_factory=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pyocd_ft232r", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    chk = sub.add_parser("check", help="run the SWDIO loopback self-test")
    chk.add_argument("serial", nargs="?", help="USB serial number (default: the only adaptor)")
    chk.add_argument("--pins", default=os.environ.get("PYOCD_FT232R_PINS", ""),
                     help="swclk=0,swdio_out=1,swdio_in=3[,nreset=N]")
    args = ap.parse_args(argv)

    devices = list_adaptors() if adaptors is None else adaptors
    if args.cmd is None:
        if not devices:
            print("No FT232R adaptors found (VID:PID 0403:6001). Check `lsusb` and USB permissions.")
            return 1
        for d in devices:
            print(f"{d['serial']}  {d['description']}  {d['url']}")
        print("Select one with:  -u ft232r:<serial>   (or -u ft232r: for the first)")
        return 0

    if args.serial:
        devices = [d for d in devices if d["serial"].lower() == args.serial.lower()]
    if len(devices) != 1:
        print(f"expected exactly one matching adaptor, found {len(devices)}; pass its serial number")
        return 1
    pins = Pins.parse(args.pins)
    make = transport_factory or (lambda url, p: FtdiTransport(url, p))
    t = make(devices[0]["url"], pins)
    idle = (1 << pins.nreset) if pins.nreset is not None else 0
    try:
        t.open(250_000, idle)
    except CalibrationError as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        t.close()
    print(f"OK: loopback works. Sample lag {t.lag} byte(s) (handled automatically), "
          f"{t.sample_hz:.0f} samples/s => SWD clock about {t.sample_hz / 2 / 1000:.0f} kHz.")
    print("This checks the FT232R and the SWDIO resistor bridge only; it does not talk to a target.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
