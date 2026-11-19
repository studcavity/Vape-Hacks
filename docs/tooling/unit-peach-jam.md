---
type: Reference
title: "Unit: Peach Jam"
description: "The unit nicknamed Peach Jam, the first unit we dumped and probed: its flash dump hash and option bytes, and the open question whether it is the source of the other DPIDR."
tags: [tooling, swd, unit]
status: draft
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T12:30:00Z" }
sources:
  - id: checkpoint
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/2026-11-17-session-checkpoint.md
    title: Checkpoint 2026-11-17 (first dump, option bytes)
  - id: flash-tool
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/tools/lb_flash.py
    title: lb_flash.py (watch and dump)
---

"Peach Jam" is the name we use for the first unit we probed and dumped, so a note about it is not confused with
[orange fucking fab](unit-orange-fab.md), the canary. The 2026-11-17 checkpoint calls it "the canary"; it has
since been renamed in these notes.[^checkpoint]

**Flash dump.** SHA-256 `c83dfe6d26adbf7bf54cd09354b792de3def21fb154a62a38037d08ea12ea254`, 65536 bytes from `0x08000000`,
two reads in one session and a third in another session agreeing. The file is only on the user's own machine, not in the repo.
It is the original firmware (initial stack pointer `0x20000A78`, reset vector `0x080000D9`) and, per the checkpoint, identical to the repository's
upstream `backup_flash.bin` except 5 bytes at `0xF004` to `0xF011`.[^checkpoint] The user confirmed this hash on 2026-11-19.

**Option bytes** (checkpoint, `options`, verified then): user word `0x0155FEAA` valid, RDP level 0, NRST is a GPIO, IWDG and
WWDG are software, BOR off, no write protection.[^checkpoint]

**DPIDR: not recorded.** Nobody wrote down the DPIDR that `watch` printed for this unit, and this repository does not hold
it. The user suspects it is the other value that `lb_flash.py watch` prints a note about: the tool expects `0x0BB11477`,
while [orange fucking fab](unit-orange-fab.md) answered with `0x0BC11477`.[^flash-tool] That is a hypothesis. To settle it, run `watch`
on Peach Jam and record what it prints. The checkpoint says the `watch` numbers were not recorded. Nothing in `dump` depends on the answer.

The checkpoint also states that nothing had been flashed to it by 2026-11-17; whether it has been since is not recorded here.

[^checkpoint]: Checkpoint 2026-11-17 (first dump, option bytes)
[^flash-tool]: lb_flash.py (watch and dump)
