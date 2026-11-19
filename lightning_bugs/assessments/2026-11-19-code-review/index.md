---
okf_version: "0.3"
title: "Lightning Bugs code review, 2026-11-19"
description: "A read-through review of lightning_bugs (firmware, host tools, flash wrapper, setup): which defects are fixed or still open, and the unverified risks; consult it before changing sync, power or flash code."
---

# Lightning Bugs code review, 2026-11-19

Exhaustive read-through of `lightning_bugs/` (firmware, host tools, flash wrapper, setup) by an LLM reviewer, written for a reader new to embedded work. **Nothing here was run on hardware**; see each concept's `confidence`. Status as of 2026-11-19: four defects fixed, three open.

## Start here
* [Overview](overview.md) - What matters most in the Lightning Bugs code review, and what to do next.

## Open defects
* [Show timing breaks after 24.8 days without a visit](defect-tick-wrap-24-days.md) - lbMasterUs uses a signed 32-bit millisecond offset, so master time jumps back 2^32 ms after 24.8 days.
* [Unit can enter STOP while USB power is present](defect-sleep-with-usb-present.md) - USB wake is rising-edge only and enterStopUntilWake clears the wake flag first, so an edge just before sleep is lost.
* [Syncs are not acknowledged during the low-battery window or boot guard](defect-sync-ignored-in-window.md) - holdWindow and lbBootGuard never call lbPoll, so a sync written then is not adopted until later.

## Fixed defects (deprecated, kept as a record)
* [resync on a power-cycled unit silently loses the show schedule](defect-resync-fallback-grid.md) - The fallback full sync takes the grid from a rebooted block, which holds the 0.5 s default, so the unit plays shows back-to-back.
* [LEDs can stay lit after a mid-show resync](defect-led-lit-after-resync.md) - playShow returns false without blanking; if the new grid is between shows, the driver stays powered with the last frame showing.
* [The flash command does not disable pyocd auto_unlock](defect-flash-auto-unlock.md) - lb_flash.py claims the flash step never mass-erases, but the pyocd flash command keeps the default auto_unlock=True.
* [Flash does not verify what is running afterwards, and --bin checks the wrong source](defect-flash-no-result-check.md) - After flashing, reconnect checks only log the sync block; with --bin, the source scan reads the current tree, not the binary.

## Risks (unverified, need hardware or a decision)
* [Hardware and firmware risks that need a unit to settle](risks-hardware.md) - Unverified assumptions in the firmware, namely power use, STOP wake-up, debug bits, sensors, LED driver, watchdog.
* [Tooling and supply-chain risks](risks-tooling.md) - Unpinned inputs to setup.sh, a heuristic safety scan, self-declared canaries and other tooling weaknesses.
