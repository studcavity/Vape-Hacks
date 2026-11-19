---
type: Assessment
title: Review overview
description: What matters most in the Lightning Bugs code review, and what to do next.
tags: [review,lightning-bugs]
status: draft
confidence: read-only except where a concept says confirmed
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../firmware/lightning_bugs/lightning_bugs.ino
  - resource: ../../firmware/lightning_bugs/lb_sync.h
  - resource: ../../host/lb_sync.py
  - resource: ../../tools/lb_flash.py
---

# Scope and method

All of `lightning_bugs/` was read: firmware (`lb_sync.h`, `lightning_bugs.ino`, `lb_power_policy.h`), host tools (`lb_sync.py`, `lb_catalog.py`, `lb_compat.py`), `tools/lb_flash.py`, `lb_stack.py`, `setup.sh`, and the assessment docs. The test suite was run (281 passed, 2 skipped). The firmware was not built and no unit was involved. Only the `resync` fallback bug was reproduced, in the simulator; every other finding is from reading the code.

# What matters most if you are new to embedded

1. **Nothing has run on a real unit.** All tests use a simulated device or fake `pyocd` and `arduino-cli`. Green tests show the logic is self-consistent, not that the chip behaves as assumed.
2. **The recovery plan was not fully built.** [swd-recovery](../swd-recovery.md) proposed a watchdog, a forced-reset button and a self-healing SWD check. Its status boxes are unticked.
3. **The reset pin is unusable.** The [session checkpoint](../2026-11-17-session-checkpoint.md) records that `options` showed NRST is a plain GPIO on this unit, so connect-under-reset is not available.
4. **The firmware uses STOP mode anyway** (`lightning_bugs.ino`, `enterStopUntilWake`, with `lb-allow-swd-risk` waivers). If STOP or its wake-up misbehaves, recovery means disconnecting the battery. Keep to the canary-first process.
5. **About 2,000 lines of host tooling support about 560 lines of firmware.** `lb_compat.py` and `lb_catalog.py` are a generic framework for one wire format, one model and one transport. That is typical LLM scope growth and makes the project harder to read.

# Suggested next steps

1. Fix the first, third, sixth and seventh defects (small, testable): [fallback grid](defect-resync-fallback-grid.md), [lit LEDs](defect-led-lit-after-resync.md), [auto_unlock](defect-flash-auto-unlock.md), [result check](defect-flash-no-result-check.md).
2. Do the canary flash with the existing process. Do not use a sealed unit until STOP wake-up, SWD-after-sleep and idle current are answered on the canary ([hardware risks](risks-hardware.md)).
3. Decide whether to build the watchdog and forced-reset mitigations, or drop STOP mode. Today the firmware does the thing the recovery plan was written to protect against, without its safety net.
4. Address the remaining defects: [24.8-day wrap](defect-tick-wrap-24-days.md), [sleep on USB](defect-sleep-with-usb-present.md), [window syncs](defect-sync-ignored-in-window.md).
