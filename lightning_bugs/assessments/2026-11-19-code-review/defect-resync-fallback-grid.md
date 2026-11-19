---
type: Defect
title: resync on a power-cycled unit silently loses the show schedule
description: The fallback full sync takes the grid from a rebooted block, which holds the 0.5 s default, so the unit plays shows back-to-back.
tags: [host,lb_sync,battery]
status: draft
confidence: confirmed in the simulator
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../host/lb_sync.py
  - resource: ../../firmware/lightning_bugs/lb_sync.h
---

# Problem

`cmd_resync` (`host/lb_sync.py`, the `if not prev.synced` branch) falls back to a full sync and, when no grid option is given, reuses "the device's grid": `prev.period_us` and `prev.epoch_us`. After a power cycle those are the firmware defaults (`LB_DEFAULT_PERIOD_US` = 500000 µs, epoch 0), not the hourly grid the user had set.

# Failure

Plain `lb_sync.py resync` on a power-cycled unit writes a 120 BPM grid. A show lasts 5.85 s, so a new show starts every 0.5 s and the unit never goes dark between shows. That drains the battery and is the opposite of the hourly design. The README says only "falls back to a full sync", and no message warns about the grid.

Reproduced: an unsynced simulated unit, `resync` with no grid arguments, ends with `period_us = 500000`, `epoch = 0`.

# Fix options

- Refuse the fallback unless a grid is given, when the block shows no host write since boot (`seq == 0`). After a low-battery STOP wake the block keeps its real grid (`seq != 0`), so keeping it is right there.
- Always require `--every`, `--bpm` or `--period-ms` on fallback.

# Resolution

Fixed on branch `sbx/jolly-shannon/02-review-doc-and-fixes`: `cmd_resync` now refuses the fallback with a message naming `--every`, `--bpm` and `--period-ms` when no host has written to the block since boot (`seq == 0`) and no grid is given. A unit woken from low-battery STOP keeps its grid. Tests: `ResyncTests.test_fallback_after_boot_refuses_to_guess_the_grid` and `test_fallback_after_sleep_wake_keeps_the_grid_it_still_holds`.
