#!/usr/bin/env python3
"""lb_flash.py — safety check, build and flash wrapper for Lightning Bugs.

Implements step 3 of assessments/swd-recovery.md:

  check   scan the sketch source for things that can cost us SWD
  build   run the check, then compile with arduino-cli (and check the binary)
  watch   poll the chip's SWD debug port ~800 times a second and report when it answers and for how long
          (finds out whether a connect window exists and how long it is; reads no flash, halts nothing)
  dump    read the whole flash over SWD (twice by default, compared), and save it (do this before flashing a unit)
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
import os
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
# with --fqbn. Run `arduino-cli board listall PY32` to find yours.
DEFAULT_FQBN = "PY32Duino:PY32:GenF030:pnum=PY32F030x8"
DEFAULT_TARGET = "py32f030x8"
DEFAULT_FREQ = 500_000
FLASH_BASE = 0x0800_0000
FLASH_SIZE = 64 * 1024           # PY32F030x8; override with `dump --size`
DUMP_DIR = ROOT / "backups"      # git-ignored (*.bin); copy dumps somewhere durable
DUMP_CHUNK = 1024

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

# Symbols that must not appear in the linked ELF. HAL_RCC_OscConfig/ClockConfig
# are deliberately NOT listed: the core's own boot-time SystemClock_Config()
# links them into every sketch (verified: they are present in the stock build).
BINARY_SYMBOL_RULES = r"(HAL_FLASHEx_OB|HAL_FLASH_OB_Launch|HAL_PWR_Enter(STOP|STANDBY))"
# Flash-unlock key values (STM32-family; assumed the same on PY32). Little-endian in .bin.
UNLOCK_KEYS = {
    "FLASH_KEY1 0x45670123": bytes.fromhex("23016745"),
    "FLASH_KEY2 0xCDEF89AB": bytes.fromhex("AB89EFCD"),
    "OPT_KEY1   0x08192A3B": bytes.fromhex("3B2A1908"),
    "OPT_KEY2   0x4C5D6E7F": bytes.fromhex("7F6E5D4C"),
}


class Fail(Exception):
    pass


class Fatal(Fail):
    """A failure that retrying cannot fix (no probe, pyocd missing). `dump --poll` gives up on these at once."""


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


def arduino_data_dir() -> Path:
    """Where arduino-cli keeps cores and toolchains: $ARDUINO_DIRECTORIES_DATA (which arduino-cli itself
    honours, and which `setup.sh --i-know-this-modifies-my-system` points inside the repo), else ~/.arduino15."""
    env = os.environ.get("ARDUINO_DIRECTORIES_DATA")
    return Path(env) if env else Path.home() / ".arduino15"


def check_binary(elf: Path | None, binf: Path) -> list[str]:
    problems = []
    if elf and elf.exists():
        nm = shutil.which("arm-none-eabi-nm") or next(
            iter(sorted(arduino_data_dir().glob("packages/**/arm-none-eabi-nm"))), None)
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


# ─── dump ────────────────────────────────────────────────────────────────────
def read_flash_passes(args, size: int, passes: int = 1) -> list[bytes]:
    """`passes` reads of the flash in ONE attach-only session (no halt, no reset, no unlock). Several reads in
    one session matter when the link only exists for a short window."""
    import lb_sync
    ns = argparse.Namespace(probe=args.probe, frequency=args.frequency, target=args.target)
    try:
        with lb_sync.open_session(ns) as session:
            target = session.board.target
            images = []
            for _ in range(passes):
                out = bytearray()
                for off in range(0, size, DUMP_CHUNK):
                    out += bytes(target.read_memory_block8(FLASH_BASE + off, min(DUMP_CHUNK, size - off)))
                images.append(bytes(out))
            return images
    except lb_sync.SyncError as e:       # no probe, or pyocd not installed: nothing to wait for
        raise Fatal(f"could not read flash over SWD: {e}")
    except Fail:
        raise
    except Exception as e:
        raise Fail(f"could not read flash over SWD: {e}")


def read_flash(args, size: int) -> bytes:
    """One pass over the flash in its own session."""
    return read_flash_passes(args, size, 1)[0]


def poll_flash(args, size: int, passes: int, timeout: float) -> list[bytes]:
    """Retry connecting in this one process (about 85 ms per attempt, against ~1 s when a shell loop starts
    Python each time) until the chip answers, then take all `passes` reads in that same session. Meant for a
    unit that only answers SWD for a short window after being woken."""
    import logging
    pyocd_log = logging.getLogger("pyocd")
    old_level, deadline = pyocd_log.level, time.monotonic() + timeout
    log(f"polling for the chip for up to {timeout:.0f} s: wake the unit now (slide switch). Ctrl-C to stop.")
    attempts, last = 0, "no answer"
    pyocd_log.setLevel(logging.CRITICAL)      # every failed attempt would otherwise print pyocd's error
    try:
        while True:
            attempts += 1
            try:
                images = read_flash_passes(args, size, passes)
                log(f"connected on attempt {attempts}")
                return images
            except Fatal:
                raise
            except Fail as e:
                last = str(e)
            if time.monotonic() >= deadline:
                raise Fail(f"no usable read in {timeout:.0f} s ({attempts} attempts); last error: {last}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        raise Fail(f"interrupted after {attempts} attempts; last error: {last}")
    finally:
        pyocd_log.setLevel(old_level)


def cmd_dump(args) -> Path:
    size, passes = args.size, args.passes
    if passes < 1:
        raise Fail("--passes must be at least 1")
    if args.poll:
        images = poll_flash(args, size, passes, args.poll_timeout)
    else:
        images = [read_flash(args, size) for _ in range(passes)]
    first = images[0]
    if any(img != first for img in images[1:]):
        raise Fail("two reads of the flash differ: unstable SWD link (check wiring, lower --frequency); "
                   "nothing saved")
    if len(set(first)) == 1:
        raise Fail(f"flash reads as all 0x{first[0]:02X}: the chip is blank, read-protected or the read failed; "
                   "nothing saved. This is NOT a usable backup")
    digest = hashlib.sha256(first).hexdigest()
    if args.output:
        out = Path(args.output)
    else:
        DUMP_DIR.mkdir(exist_ok=True)
        out = DUMP_DIR / f"dump_{time.strftime('%Y%m%dT%H%M%S')}_{digest[:12]}{'' if passes > 1 else '_unverified'}.bin"
    if out.exists():
        raise Fail(f"{out} already exists; refusing to overwrite a backup")
    out.write_bytes(first)
    if passes > 1:
        log(f"dumped {size} bytes from 0x{FLASH_BASE:08x}, {passes} identical reads, sha256 {digest}")
    else:
        log(f"dumped {size} bytes from 0x{FLASH_BASE:08x}, ONE read only (not cross-checked), sha256 {digest}")
        log("Dump again later and compare the sha256 values before trusting this as a backup.")
    log(f"saved {out}")
    log("Copy it somewhere durable before this machine goes away (a sandbox's files are lost when it exits).")
    return out


# ─── watch ───────────────────────────────────────────────────────────────────
WATCH_GAP_FAILS = 5        # consecutive failed attempts (~6 ms) that end an "answering" window
DPIDR_CORTEX_M0P = 0x0BB11477


def raw_attempt(probe) -> int:
    """One SWD line reset + JTAG-to-SWD switch + DP IDR read. Returns the DPIDR; raises when nothing ACKs."""
    probe.swj_sequence(51, 0xFFFFFFFFFFFFFF)
    probe.swj_sequence(16, 0xE79E)
    probe.swj_sequence(51, 0xFFFFFFFFFFFFFF)
    probe.swj_sequence(8, 0x00)
    return probe.read_dp(0, now=True)


def valid_dpidr(v: int) -> bool:
    """A real DPIDR has bit 0 set; an all-ones read is a floating line, not a chip."""
    return bool(v & 1) and v != 0xFFFFFFFF


def run_watch(probe, timeout: float, clock=time.monotonic, report=log) -> list[dict]:
    """Poll the probe until `timeout` or Ctrl-C. Returns one dict per window in which the chip answered."""
    start = clock()
    windows, cur, fails, attempts, last_note = [], None, 0, 0, start

    def close(w):
        w["ms"] = (w["last"] - w["first"]) * 1000
        windows.append(w)
        report(f"  window {len(windows)}: answered from +{w['first'] - start:.3f} s for {w['ms']:.0f} ms "
               f"({w['reads']} reads), DPIDR 0x{w['dpidr']:08X}")
    try:
        while clock() - start < timeout:
            attempts += 1
            try:
                v = raw_attempt(probe)
                ok = valid_dpidr(v)
            except Exception:
                ok = False
            now = clock()
            if ok:
                fails = 0
                if cur is None:
                    cur = {"first": now, "last": now, "reads": 0, "dpidr": v}
                    report(f"  chip answered at +{now - start:.3f} s, DPIDR 0x{v:08X}")
                cur["last"], cur["reads"] = now, cur["reads"] + 1
            else:
                fails += 1
                if cur is not None and fails >= WATCH_GAP_FAILS:
                    close(cur)
                    cur = None
            if cur is None and now - last_note >= 10:
                report(f"  still no answer ({attempts} attempts, {now - start:.0f} s)")
                last_note = now
    except KeyboardInterrupt:
        report("interrupted")
    if cur is not None:
        close(cur)
    report(f"{attempts} attempts in {clock() - start:.1f} s, {len(windows)} window(s)"
           + (f", longest {max(w['ms'] for w in windows):.0f} ms" if windows else ""))
    return windows


def open_raw_probe(args):
    """The Pico (or the one named by --probe), opened for raw SWD access only: no target, no unlock."""
    try:
        from pyocd.core.helpers import ConnectHelper
        from pyocd.core.session import Session
        from pyocd.probe.debug_probe import DebugProbe
    except ImportError:
        raise Fatal("pyocd is not installed: pip install pyocd")
    probes = ConnectHelper.get_all_connected_probes(blocking=False)
    if args.probe:
        probes = [p for p in probes if p.unique_id == args.probe]
    if not probes:
        raise Fatal("no debug probe found (pyocd list shows what is connected)")
    probe = probes[0]
    Session(probe, options={"frequency": args.frequency, "target_override": args.target})   # pyocd needs one
    probe.open()
    probe.connect(DebugProbe.Protocol.SWD)
    probe.set_clock(args.frequency)
    return probe


def cmd_watch(args) -> None:
    import logging
    pyocd_log = logging.getLogger("pyocd")
    old_level = pyocd_log.level
    pyocd_log.setLevel(logging.CRITICAL)      # each failed attempt would otherwise print pyocd's error
    probe = open_raw_probe(args)
    log(f"watching the SWD port of probe {probe.unique_id} for up to {args.timeout:.0f} s at "
        f"{args.frequency // 1000} kHz: wake the unit now (slide switch or charger). Ctrl-C to stop.")
    try:
        windows = run_watch(probe, args.timeout)
    finally:
        pyocd_log.setLevel(old_level)
        try:
            probe.disconnect()
            probe.close()
        except Exception:
            pass
    if not windows:
        raise Fail("the chip never answered")
    odd = {w["dpidr"] for w in windows} - {DPIDR_CORTEX_M0P}
    if odd:
        log("note: expected DPIDR 0x%08X for a Cortex-M0+; saw %s" % (DPIDR_CORTEX_M0P, sorted(hex(x) for x in odd)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fqbn", default=DEFAULT_FQBN, help=f"arduino-cli board (default {DEFAULT_FQBN})")
    ap.add_argument("--target", "-t", default=DEFAULT_TARGET)
    ap.add_argument("--probe", "-u", help="debug probe unique id")
    ap.add_argument("--frequency", "-f", type=int, default=DEFAULT_FREQ)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="source safety check only")
    sub.add_parser("build", help="check, compile, check binary")
    wp = sub.add_parser("watch", help="poll the SWD port and report when/for how long the chip answers")
    wp.add_argument("--timeout", type=float, default=60.0, metavar="SECONDS", help="stop after this long (default 60)")
    dp = sub.add_parser("dump", help="read the flash twice, compare, save a backup")
    dp.add_argument("--output", "-o", help="file to write (default backups/dump_<time>_<sha>.bin; never overwritten)")
    dp.add_argument("--size", type=lambda s: int(s, 0), default=FLASH_SIZE,
                    help=f"bytes to read from 0x{FLASH_BASE:08x} (default {FLASH_SIZE})")
    dp.add_argument("--passes", type=int, default=2,
                    help="reads to take and compare (default 2). 1 is for a short SWD window: the file is named "
                         "*_unverified.bin; confirm it with a second dump")
    dp.add_argument("--poll", action="store_true",
                    help="keep retrying the connection in this process (about 12 attempts/s) until the chip "
                         "answers, then read at once. For a unit that only answers SWD briefly after waking")
    dp.add_argument("--poll-timeout", "--timeout", type=float, default=120.0, metavar="SECONDS",
                    help="give up after this long with --poll (default 120)")
    fp = sub.add_parser("flash", help="check, build, flash, verify reconnect")
    fp.add_argument("--canary", action="store_true", help="this unit is a canary (recoverable without opening)")
    fp.add_argument("--yes", action="store_true", help="don't prompt before flashing a sealed unit")
    fp.add_argument("--bin", help="flash an existing .bin instead of building")
    args = ap.parse_args()
    try:
        {"check": cmd_check, "build": cmd_build, "watch": cmd_watch, "dump": cmd_dump, "flash": cmd_flash}[args.cmd](args)
    except Fail as e:
        log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
