---
type: Reference
title: "Unit: orange fucking fab"
description: "What we have observed about the unit nicknamed orange fucking fab: its SWD connect windows and DPIDR, and that no tool gates on the chip ID."
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

"orange fucking fab" is the name we use for one physical unit, so a note about it is not confused with the earlier unit we
ran `watch` on. Everything here was observed on 2026-11-19 through the Pico probe wired as in [the wiring note](swd-wiring.md).
The `watch` output was read from a terminal in the session and was not saved to a file.

**Observed with `watch --timeout 90`** at 500 kHz, moving the slide switch during the run:[^flash-tool]

| Window | Started | Lasted | DPIDR |
|---|---|---|---|
| 1 | +14.3 s | 44.4 s | `0x0BC11477` |
| 2 | +64.4 s | 17.1 s | `0x0BC11477` |

Between the windows the chip did not answer. A `dump --poll --timeout 60` run earlier, with nobody moving the switch, found
no chip in 60 s (542 attempts), so on this unit a connect window follows a switch move and the dump has to be started first.

**The DPIDR differs from what `watch` expects.** `lb_flash.py` compares against `0x0BB11477` and prints a note when it
sees something else. That note is informational only. The earlier unit's DPIDR is not recorded anywhere in this repository, so
whether the two units really differ, or the constant in the tool is wrong, is not settled. (Unsourced recollection: `0x0BC11477`
is the usual ID for a Cortex-M0+ and `0x0BB11477` for a plain Cortex-M0. Check it against the Arm documentation before changing the constant.)

**Nothing gates on the chip ID.** `dump` checks only that the reads agree, that the data is not all `0x00` or `0xFF`,
and that the output file does not exist yet.[^flash-tool] `watch` only prints the note above. So a different DPIDR does not stop a
backup.

**Not yet done on this unit:** a flash dump, and any reading of its option bytes. This note does not say whether it is the canary.

[^flash-tool]: lb_flash.py (watch and dump)
