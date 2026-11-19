---
type: Reference
title: "Unit: Peach Jam"
description: "The unit nicknamed Peach Jam, the first unit we dumped and probed: its flash dump hash and option bytes, its DPIDR and UID."
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

**Second dump, 2026-11-19** (`dump --poll --timeout 60`, connected on attempt 415, two identical reads): SHA-256
`1b6d165a69591f54cb01098b0b949965e5b757e19afb0dfa6993d9b726858706`, saved on the sandbox as `lightning_bugs/backups/dump_20261119T062003_1b6d165a6959.bin`
(git-ignored, not committed). It differs from the repository's upstream `backup_flash.bin` in exactly 5 bytes, 3 at `0xF004` and 2 at `0xF010`
(value `0x000BD0FF` there, then `0x1864`), which is what the checkpoint says of the first dump.[^flash-tool] Its code, stack pointer and reset vector are
the upstream image's. It does **not** match the first dump's hash (`c83dfe6d…`), and the likely reason is the `0xF000` page: the two values look like counters the stock firmware
rewrites, so a unit's hash can change as it is used. That is a guess; with the first dump file (the user has it) the two can be compared byte for byte. That the unit wired for this
dump is Peach Jam rests on the user's word and on its UID differing from orange's. Its code differs from orange's by about 2.3 KB (see [orange fucking fab](unit-orange-fab.md)).

**Option bytes** (checkpoint, `options`, verified then): user word `0x0155FEAA` valid, RDP level 0, NRST is a GPIO, IWDG and
WWDG are software, BOR off, no write protection.[^checkpoint]

**DPIDR and UID** (2026-11-19, `watch --timeout 15`, two connect windows of 3.1 s and 8.6 s): DPIDR `0x0BC11477`, the same as
[orange fucking fab](unit-orange-fab.md), so Peach Jam is not the source of a different value.[^flash-tool] Chip UID words
`41503456 35333815 00b2e84c 47047c78`, which differ from orange's `35355041 18383439 54bdc600 78ad0547`. Which unit was wired was the user's word; the
differing UID shows it was not orange. The 2026-11-17 checkpoint did not record the earlier `watch` numbers.

The checkpoint also states that nothing had been flashed to it by 2026-11-17; whether it has been since is not recorded here.

[^checkpoint]: Checkpoint 2026-11-17 (first dump, option bytes)
[^flash-tool]: lb_flash.py (watch and dump)
