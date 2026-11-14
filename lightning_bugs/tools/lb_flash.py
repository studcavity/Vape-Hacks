#!/usr/bin/env python3
"""lb_flash.py — safety check, build and flash wrapper for Lightning Bugs.

Implements step 3 of assessments/swd-recovery.md:

  check   scan the sketch source for things that can cost us SWD
  build   run the check, then compile with arduino-cli (and check the binary)
  flash   run check + build, flash over SWD, then confirm we can still reconnect
          (in the boot guard, after the guard, and 30 s later)

Canary policy: a build must be flashed to a canary unit (one you can power-cycle
or reset) with `flash --canary` and pass the reconnect checks before it can be
flashed to a sealed unit. The build's SHA-256 is recorded in .lb_canary.json.
The wrapper cannot tell units apart on its own, so --canary is your declaration.

Nothing here writes option bytes, and the flash step never mass-erases.

Register/pin details in the check patterns are from family knowledge and have
NOT been verified against the reference manual.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH_DIR = ROOT / "firmware" / "lightning_bugs"
BUILD_DIR = ROOT / "build"
CANARY_FILE = ROOT / ".lb_canary.json"
sys.path.insert(0, str(ROOT / "host"))

# The py32duino board identifier depends on how the core was installed; override
# with --fqbn. Run `arduino-cli board listall py32` to find yours.
DEFAULT_FQBN = "py32:py32:PY32F030X8"
DEFAULT_TARGET = "py32f030x8"
DEFAULT_FREQ = 500_000

ALLOW = "lb-allow-swd-risk"   # put in a comment on the same line to waive a rule

# (regex, why). Matched against source with comments stripped, unless the raw
# line carries ALLOW.
SOURCE_RULES = [
    (r"\bPA1[34]\b", "uses PA13/PA14 (SWDIO/SWCLK)"),
    (r"\bGPIOA\s*->\s*(MODER|AFR\w*|OTYPER|OSPEEDR|PUPDR)\b", "raw GPIOA mode/alternate-function write"),
    (r"\bSLEEPDEEP\b|\bSCB\s*->\s*SCR\b", "deep-sleep bits"),
    (r"\bHAL_PWR_Enter(STOP|STANDBY)\w*|\bPWR_(CR|SR)\b|\bEnterSTOP|\bEnterSTANDBY", "STOP/STANDBY entry"),
    (r"\b(FLASH_OB\w*|HAL_FLASHEx_OB\w*|OPTKEY\w*|OPTR\b|FLASH->(OPTKEYR|OPTR|KEYR|CR|SR|ACR))", "flash/option-byte access"),
    (r"\bRCC\s*->\s*(CR|CFGR|ICSCR|CSR|BDCR)\b|\bHAL_RCC_\w*|\bSystemClock_Config\b",
     "clock configuration (never switch the system clock to LSI/LSE or slow it)"),
    (r"\bDBGMCU\b", "debug-MCU configuration (must be reviewed by a person)"),
]

# Symbols that must not appear in the linked ELF.
BINARY_SYMBOL_RULES = r"(HAL_FLASHEx_OB|HAL_FLASH_OB_Launch|HAL_PWR_Enter(STOP|STANDBY)|HAL_RCC_OscConfig)"
# Flash-unlock key values (STM32-family; assumed the same on PY32). Little-endian in .bin.
UNLOCK_KEYS = {
    "FLASH_KEY1 0x45670123": bytes.fromhex("23016745"),
    "FLASH_KEY2 0xCDEF89AB": bytes.fromhex("AB89EFCD"),
    "OPT_KEY1   0x08192A3B": bytes.fromhex("3B2A1908"),
    "OPT_KEY2   0x4C5D6E7F": bytes.fromhex("7F6E5D4C"),
}


class Fail(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


# ─── check ───────────────────────────────────────────────────────────────────
def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def check_source() -> list[str]:
    problems = []
    for path in sorted(SKETCH_DIR.glob("*")):
        if path.suffix not in (".ino", ".h", ".c", ".cpp", ".hpp"):
            continue
        raw = path.read_text().splitlines()
        code = strip_comments(path.read_text()).splitlines()
        for i, line in enumerate(code):
            if ALLOW in raw[i]:
                continue
            for rx, why in SOURCE_RULES:
                if re.search(rx, line):
                    problems.append(f"{path.relative_to(ROOT)}:{i + 1}: {why}: {raw[i].strip()}")
    return problems


def check_binary(elf: Path | None, binf: Path) -> list[str]:
    problems = []
    if elf and elf.exists():
        nm = shutil.which("arm-none-eabi-nm") or next(
            iter(sorted(Path.home().glob(".arduino15/packages/**/arm-none-eabi-nm"))), None)
        if nm:
            out = subprocess.run([str(nm), str(elf)], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if re.search(BINARY_SYMBOL_RULES, line):
                    problems.append(f"{elf.name}: forbidden symbol linked: {line.split()[-1]}")
        else:
            log("warning: arm-none-eabi-nm not found; skipping symbol check")
    data = binf.read_bytes()
    for name, pat in UNLOCK_KEYS.items():
        if pat in data:
            problems.append(f"{binf.name}: contains flash unlock key {name}")
    return problems


def cmd_check(_args) -> None:
    problems = check_source()
    if problems:
        log("SAFETY CHECK FAILED:")
        for p in problems:
            log("  " + p)
        log(f"(a deliberate exception needs `// {ALLOW}` on that line)")
        raise Fail("source safety check failed")
    log("source safety check: ok")


# ─── build ───────────────────────────────────────────────────────────────────
def cmd_build(args) -> Path:
    cmd_check(args)
    cli = shutil.which("arduino-cli")
    if not cli:
        raise Fail("arduino-cli not found (install it, then `arduino-cli core install` the py32duino core)")
    BUILD_DIR.mkdir(exist_ok=True)
    cmd = [cli, "compile", "--fqbn", args.fqbn, "--output-dir", str(BUILD_DIR), str(SKETCH_DIR)]
    log("$ " + " ".join(cmd))
    if subprocess.run(cmd).returncode:
        raise Fail("build failed")
    binf = BUILD_DIR / "lightning_bugs.ino.bin"
    elf = BUILD_DIR / "lightning_bugs.ino.elf"
    if not binf.exists():
        raise Fail(f"expected {binf} after build; not found")
    problems = check_binary(elf, binf)
    if problems:
        log("BINARY SAFETY CHECK FAILED:")
        for p in problems:
            log("  " + p)
        raise Fail("binary safety check failed")
    log(f"binary safety check: ok ({binf.stat().st_size} bytes)")
    return binf


# ─── flash ───────────────────────────────────────────────────────────────────
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_canary() -> dict:
    try:
        return json.loads(CANARY_FILE.read_text())
    except (OSError, ValueError):
        return {}


def verify_connect(args, label: str) -> None:
    """Attach (no halt, no reset, no unlock) and find the sync block."""
    import lb_sync
    ns = argparse.Namespace(probe=args.probe, frequency=args.frequency, target=args.target)
    with lb_sync.open_session(ns) as session:
        dev = lb_sync.Device(session.board.target)
        blk = dev.read_block()
        log(f"  [{label}] SWD ok, sync block at 0x{dev.addr:08x}, hold={blk.hold}")


def verify_retry(args, label: str, timeout: float) -> None:
    end = time.monotonic() + timeout
    while True:
        try:
            return verify_connect(args, label)
        except Exception as e:
            if time.monotonic() >= end:
                raise Fail(f"[{label}] could not reconnect over SWD: {e}")
            time.sleep(0.3)


def cmd_flash(args) -> None:
    pyocd = shutil.which("pyocd")
    if not pyocd:
        raise Fail("pyocd not found (pip install pyocd, plus the Puya pack for py32f030x8)")
    if args.bin:
        binf = Path(args.bin)
        cmd_check(args)
        problems = check_binary(None, binf)
        if problems:
            raise Fail("binary safety check failed: " + "; ".join(problems))
    else:
        binf = cmd_build(args)
    digest = sha(binf)
    canary = load_canary()
    if not args.canary and digest not in canary:
        raise Fail("this build has not passed on a canary unit.\n"
                   "  Flash it to a canary first:  lb_flash.py flash --canary ...\n"
                   "  (a canary is a unit you can power-cycle or reset without opening it)")
    if not args.canary and not args.yes:
        if input("Flash a SEALED unit with this canary-tested build? [y/N] ").strip().lower() != "y":
            raise Fail("aborted")

    probe = ["-u", args.probe] if args.probe else []
    cmd = [pyocd, "flash", "-t", args.target, "-f", str(args.frequency), *probe,
           "--base-address", "0x08000000", str(binf)]
    log("$ " + " ".join(cmd))
    if subprocess.run(cmd).returncode:
        raise Fail("pyocd flash failed")

    log("Resetting and verifying SWD stays reachable...")
    subprocess.run([pyocd, "reset", "-t", args.target, "-f", str(args.frequency), *probe])
    time.sleep(0.5)
    verify_retry(args, "boot guard", 5)           # guard holds the chip for 3 s
    time.sleep(4)
    verify_retry(args, "after guard", 5)
    log("  waiting 30 s...")
    time.sleep(30)
    verify_retry(args, "after 30 s", 5)

    if args.canary:
        canary[digest] = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "bin": binf.name}
        CANARY_FILE.write_text(json.dumps(canary, indent=2) + "\n")
        log(f"Build {digest[:12]} recorded as canary-tested in {CANARY_FILE.name}")
    log("flash ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fqbn", default=DEFAULT_FQBN, help=f"arduino-cli board (default {DEFAULT_FQBN})")
    ap.add_argument("--target", "-t", default=DEFAULT_TARGET)
    ap.add_argument("--probe", "-u", help="debug probe unique id")
    ap.add_argument("--frequency", "-f", type=int, default=DEFAULT_FREQ)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="source safety check only")
    sub.add_parser("build", help="check, compile, check binary")
    fp = sub.add_parser("flash", help="check, build, flash, verify reconnect")
    fp.add_argument("--canary", action="store_true", help="this unit is a canary (recoverable without opening)")
    fp.add_argument("--yes", action="store_true", help="don't prompt before flashing a sealed unit")
    fp.add_argument("--bin", help="flash an existing .bin instead of building")
    args = ap.parse_args()
    try:
        {"check": cmd_check, "build": cmd_build, "flash": cmd_flash}[args.cmd](args)
    except Fail as e:
        log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
