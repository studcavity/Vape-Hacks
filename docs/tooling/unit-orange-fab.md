---
type: Reference
title: "Unit: orange fucking fab"
description: "What we have observed about the canary unit nicknamed orange fucking fab: its DPIDR, SWD connect windows, flash dump hash, and that no tool gates on the chip ID."
tags: [tooling, swd, unit]
status: draft
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T12:00:00Z" }
sources:
  - id: flash-tool
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/tools/lb_flash.py
    title: lb_flash.py (watch and dump)
  - id: wiring
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/docs/tooling/swd-wiring.md
    title: Wiring a Pico debug probe to the unit over USB-C
---

"orange fucking fab" is the name we use for the **canary** unit, so a note about it is not confused with the earlier unit
([Peach Jam](unit-peach-jam.md)). Everything here was observed on 2026-11-19 through the Pico probe wired as in [the wiring note](swd-wiring.md).
The `watch` output was read from a terminal in the session and was not saved to a file.

**Observed with `watch --timeout 90`** at 500 kHz, moving the slide switch during the run:[^flash-tool]

| Window | Started | Lasted | DPIDR |
|---|---|---|---|
| 1 | +14.3 s | 44.4 s | `0x0BC11477` |
| 2 | +64.4 s | 17.1 s | `0x0BC11477` |

Between the windows the chip did not answer. A `dump --poll --timeout 60` run earlier, with nobody moving the switch, found
no chip in 60 s (542 attempts), so on this unit a connect window follows a switch move and the dump has to be started first.

**The DPIDR matches Peach Jam's.** Both units answer `0x0BC11477`, as read by `watch` on 2026-11-19 ([Peach Jam](unit-peach-jam.md)). `lb_flash.py`
used to expect `0x0BB11477` and printed a note on every run; since both units agree, the constant was changed to `0x0BC11477`.[^flash-tool]
(Unsourced recollection: `0x0BB11477` is the plain Cortex-M0 value; check against the Arm documentation if it matters.)

**Nothing gates on the chip ID.** `dump` checks only that the reads agree, that the data is not all `0x00` or `0xFF`,
and that the output file does not exist yet.[^flash-tool] `watch` only prints the note above. So a different DPIDR does not stop a
backup.

**Flash dump** (2026-11-19, `dump --poll --timeout 60`, connected on attempt 234 after a switch move): 65536 bytes from
`0x08000000`, two identical reads, SHA-256
`d78f4a5bee8a927db42392f9d4626ef636b72787cd9a182b8703e461b562687c`. Saved on the sandbox as
`lightning_bugs/backups/dump_20261119T054158_d78f4a5bee8a.bin` (git-ignored; copy kept by the user, not in the repo).[^flash-tool]
This is the unit's original firmware, taken before any flashing. Its initial stack pointer (`0x20000A78`) and reset vector
(`0x080000D9`) match [Peach Jam](unit-peach-jam.md)'s, but it is **not** the same image as the repository's upstream
`backup_flash.bin`: 27,697 of 65,536 bytes differ (SHA-256 of that file `ca2460e4...fc35`), where Peach Jam's dump is recorded as differing from it
in 5 bytes. So this unit runs a different firmware build from Peach Jam's.[^flash-tool]

**Option bytes** (2026-11-19, `options --poll --timeout 60`, connected on attempt 35): identical to Peach Jam's.[^flash-tool]
User word `0x0155FEAA` valid, SDK word `0xFF0000FF`, write-protect word `0x0000FFFF` (none of the 16 sectors protected), RDP `0xAA` (level 0, no read
protection), NRST is a GPIO (no reset pin), IWDG and WWDG are software, BOR off, `nBOOT1` = 1. Live `FLASH_OPTR` `0x0000FEAA` matches.

**Debug bits:** `RCC_APBENR1` `0x98000000` (DBGEN set), `DBGMCU_CR` `0x00000002`, so `DBG_STOP` is **set**, as are the
freeze registers' defaults: `APB_FZ1` and `APB_FZ2` are 0. DBGMCU `IDCODE` reads `0x60001000`. The `dump` and `watch` runs earlier in the
session connected through pyocd, which sets these bits, and they stay until the battery is disconnected, so this reading does not describe the
original firmware and a sleep-current measurement taken now would include it.[^flash-tool]

**Flashed 2026-11-19:** a throwaway diagnostic build (firmware 0.5.99, build `402bd7c8`, binary hash `dfb42a9de40d`, never pushed), with
`flash --canary --bin ... --wait 90`. SWD stayed reachable in the guard, after the guard and 30 s later. The build
had no sleep and published PA2 and PA3 readings; the results are in [the mode switch note](../hardware/mode-switch.md). The unit now runs that diagnostic
build, not its original firmware (the original is the dump above). `flash` needs the venv's `pyocd` on `PATH`
(`PATH=.venv/bin:$PATH`); without it the command stops before touching the unit.[^flash-tool]

**Flashed 0.5.1 (2026-11-19):** firmware 0.5.1 (build `160f2e79`, binary hash `a386a9341d7c`), the real firmware with the
switch-off sleep, over the diagnostic build, with the switch in the middle position. SWD stayed reachable in the guard, after the guard and 30 s later.[^flash-tool]

What the user saw (and `status` confirmed with `woken from sleep 2x since boot`): moving the switch to the middle or on positions restarts the
"unsynced" blink at once with a new cadence; moving it to the off pole stops the blinking; moving it back starts it again. So the off
pole blanks the LEDs, a move off it wakes the unit, and PA2's edge works as a wake source after the analog read.

**Not shown:** real STOP behaviour. `DBG_STOP` is set (every pyocd connection sets it again), so clocks may keep running and the tick counter cannot
prove sleep (it ran continuously through a logged sleep). Not measured: sleep current, the `millis()` rate after a wake, and whether the unit
stays reachable over SWD while asleep: with the unit apparently asleep the raw SWD debug port answered but full connects failed ("Unexpected ACK 5", an invalid coresight
ROM read), which is what a stopped bus clock would look like. A run of four failed connects while the user said the switch was at "on" is unexplained: the connects worked at
the middle position and again afterwards at "on". A clean test (battery disconnect, no probe during the sleep, read the tick after the wake) is described in
[the power policy](../lightning-bugs/power-policy.md).

[^flash-tool]: lb_flash.py (watch and dump)
