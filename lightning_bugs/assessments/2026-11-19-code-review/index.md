---
okf_version: "0.2"
---

# Lightning Bugs code review, 2026-11-19

Exhaustive read-through of `lightning_bugs/` (firmware, host tools, flash wrapper, setup) by an LLM reviewer. Written for a reader new to embedded work. **Nothing here was run on hardware**; see each concept's `confidence`.

## Start here
* [Overview](overview.md) - what matters most, how to read this bundle, suggested next steps

## Defects (code does the wrong thing)
* [resync fallback loses the show schedule](defect-resync-fallback-grid.md) - power-cycled unit gets a 120 BPM grid (confirmed in the simulator)
* [Timing breaks after 24.8 days](defect-tick-wrap-24-days.md) - signed 32-bit millisecond offset wraps
* [LEDs stay lit after a mid-show resync](defect-led-lit-after-resync.md) - playShow returns without blanking
* [Unit can sleep while on USB power](defect-sleep-with-usb-present.md) - wake is edge-only and the flag is cleared first
* [Syncs ignored during the low-battery window](defect-sync-ignored-in-window.md) - no lbPoll in holdWindow or the boot guard
* [Flash command does not disable auto_unlock](defect-flash-auto-unlock.md) - contradicts "never mass-erases"
* [Flash does not check what is running afterwards](defect-flash-no-result-check.md) - and `--bin` scans the wrong source

## Risks (unverified, need hardware or a decision)
* [Hardware and firmware risks](risks-hardware.md)
* [Tooling and supply-chain risks](risks-tooling.md)
