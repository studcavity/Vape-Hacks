# Checkpoint, 2026-11-17: Pico probe bring-up, first backup, ready for a canary flash

Written at the end of a long session so the next one starts from facts, not from memory. Statements are marked
**verified** (seen on the real unit or probe), **from docs** (datasheet, manual, schematic, prior art; not yet
confirmed on our unit) or **guess**.

## Where things stand

- The FTDI probe stack is gone; the Raspberry Pi Pico running `debugprobe` v2.3.1 is the only supported probe
  (`CLAUDE.md`, "Debug probe").
- The canary's flash has been **dumped and verified**: two reads in one session and a third from a separate session
  agree. SHA-256 `c83dfe6d26adbf7bf54cd09354b792de3def21fb154a62a38037d08ea12ea254`, 65536 bytes from `0x08000000`.
  The file lives only on the user's own machine (copied out of the sandbox); it is deliberately **not** in the repo.
  It is the original firmware: vector table SP `0x20000A78`, reset `0x080000D9`, identical to the other explorer's
  `backup_flash.bin` except 5 bytes at `0xF004-0xF011` (probably per-unit data; **guess**).
- **Nothing has been flashed.** No option byte has been written. The firmware build has not been run on this branch.

## What went wrong first, and why (so it is not repeated)

The unit never answered SWD for hours of attempts. **Cause (verified by the user's report): the wires were on the three
pads labelled SWCLK/GND/SWDIO under the Pico, which are the Pico's own debug port.** The probe firmware drives
**GP2 (pin 4) = SWCLK and GP3 (pin 5) = SWDIO**. After moving the wires the chip answered at once. The README now says
so. Smaller things that cost time: my first dump command (`pyocd read`) does not exist in pinned pyocd 0.46.1; a shell
retry loop costs about 0.8 s per attempt; `-f 100000` made things slower, not safer.

## What we know about the unit

- **Access:** SWD is on the USB-C CC pins; no need to open the case. Per the BD0061 schematic (schlae/VapeRE, KiCad
  file parsed): GND is **A12/B12**, VBUS A9/B9, SWDIO on **B5**, SWCLK on **A5** (A5 for SWCLK inferred from the wire
  layout), each CC pin with a **5.1k to ground**. The Jam prior art wires them the other way round; both are right for one
  plug orientation, so swap if it will not connect. **Verified** on the user's breakout: A5-A12 about 5.1k, B5-A12 about
  4.98k.
- **Chip answers after a wake** (slide switch or briefly plugging a charger) and, per the user, **the window is long**
  (verified by `watch`; the numbers were not recorded here). It sleeps in between, so SWD is unavailable then.
- **Option bytes (verified, `options`):** user word `0x0155FEAA` valid; **RDP level 0**; **NRST is a GPIO (no reset
  pin)**; IWDG and WWDG are **software**; BOR **off**; no write protection; SDK word `0xFF0000FF` (empty area, **guess**).
- **DBGMCU:** `DBG_STOP` and `DBGEN` read as set, but pyocd's Puya pack (`DebugCoreStart`, `Puya.PY32F0xx_DFP.1.2.8`)
  writes `DBGMCU_CR = 2`, sets `DBGEN` and `DHCSR.C_DEBUGEN` on every ordinary connect, and they persist until a power-on
  reset. So that reading says nothing about the original firmware. `options` now skips that sequence for itself; `dump`,
  `lb_sync` and `flash` still use it. A `watch` run with the bit set and the unit asleep still got no answer, so
  `DBG_STOP` alone does not explain the sleep window (unresolved).
- **How the original firmware sleeps (offline disassembly, capstone; decode of data regions is junk, so treat as
  indicative):** one stop-mode function at `0x08004104` (`WFI` `0x4136`, `WFE` `0x413C/0x413E`), called from one place
  (`0x08006BC8`, main loop) only when **PA3 reads low and PF0 reads high**, after enabling the PWR clock, configuring the
  low-power timer (`0x40007C00`) and setting the low-power regulator. It never references the `DBGMCU` base. **No GPIO
  reconfiguration of PA13/PA14 in that stretch**; the rest of the firmware was not read.
- **Battery:** the unit reported 38%, which the firmware's own table puts near 3.70 V (**guess**, +/- 0.2 V from
  Vrefint calibration). **No deep-discharge protection IC is drawn in BD0061** (charger `LR5112`/TP4056-class, a P-MOSFET,
  a DP3T switch; no DW01/8205-style part), but the schematic omits the cell and coil drivers, so absence is weak
  evidence. Treat the cell as unprotected.
- **Pico limits (RP2040 datasheet, from docs):** IO pins absolute max IOVDD + 0.5 V (3.8 V at 3.3 V), no 5 V tolerance;
  the unit's SWDIO can swing to the battery voltage (up to 4.2 V). The PY32F030 reads a high at 0.7 x VCC. **Series
  resistors (about 240 ohm, 220 or 270 as a standard value) are recommended and not yet fitted.** The 5.1k CC pull-downs mean
  the prior art's 10k pull-ups only divide to about 1.1 V; do not rely on pull-ups.

## Tools added this session (all in `tools/lb_flash.py`, tested against fakes; none flashed anything)

| Command | Purpose |
|---|---|
| `dump [--passes N] [--poll] [--timeout S] [-o FILE]` | verified flash backup; `--passes 1` marks the file `*_unverified.bin` |
| `watch [--timeout S]` | raw SWD IDCODE poll (about 800/s): when the chip answers, for how long, its DPIDR |
| `options [--poll]` | option bytes, `RCC_APBENR1.DBGEN`, DBGMCU (only if the debug clock is on); reads only |
| `flash --wait [S]` | poll until the chip answers, then run `pyocd flash` once (never retried) |

Corrections to things said earlier in the session: `options` was first described as writing nothing, but the pyocd
connect it used did write DBGMCU/DBGEN (fixed, tested); `dump` and `flash` still go through that pack sequence.

## Next steps, in order

1. **Run `lb_flash.py build`** on this branch (source scan plus binary scan). Not yet seen passing here.
2. **Fit the series resistors** on SWCLK and SWDIO (Pico side, before the breakout). Re-run `watch` once to confirm the
   chip still answers.
3. **Flash the canary:** `build` first, then
   `lb_flash.py flash --canary --bin build/lightning_bugs.ino.bin --wait`, and wake the unit after starting it. Keep the
   verified dump safe first. `pyocd flash` halts on connect, which is why one connection should hold; prior art
   (Jam, hijack, C642) did the same. Watch the three post-flash reconnect checks: they are attach-only, so they depend on
   the unit being reachable then (the firmware's boot guard should help; **not yet seen on this unit**).
4. If the canary behaves for a long run, only then consider a sealed unit (`flash` refuses without a canary record).
5. **Battery safety:** the flashing session keeps the core halted (no sleep), so keep sessions short and check the unit's
   percentage first. Consider a low-voltage cutoff in our firmware (Vrefint measurement, or the PVD), since the board has no
   protection that we have found. Writing the BOR option byte is possible (levels up to 3.2 V) but a bad option write
   can set RDP level 1 and wipe the flash to undo; **no reason to write option bytes has been found**, so we have not.
6. Open questions worth an hour each: why `watch` stays silent while asleep with `DBG_STOP` set (is it the low-power
   regulator, or something else in the firmware?); read the rest of the original firmware for PA13/PA14 changes; what the
   5 differing bytes at `0xF004` are; record a `watch` window length for future reference.

## Quick reference

```sh
cd lightning_bugs
.venv/bin/python tools/lb_flash.py watch --timeout 60                       # does the chip answer, and for how long
.venv/bin/python tools/lb_flash.py options --poll                           # option bytes (wake the unit)
.venv/bin/python tools/lb_flash.py dump --poll --timeout 120                # verified backup, two passes
.venv/bin/python tools/lb_flash.py build                                    # safety scans + compile
.venv/bin/python tools/lb_flash.py flash --canary --bin build/lightning_bugs.ino.bin --wait
```

Wiring: Pico pin 4 (GP2) = SWCLK, pin 5 (GP3) = SWDIO, any Pico GND to USB-C A12; unit on its own battery; Pico VBUS
not connected to the unit; never a charger or host on the breakout while the probe is wired. Swap the two signal wires if
it will not connect. Sandbox files are lost when a session ends: copy any dump or build output out before exiting.
