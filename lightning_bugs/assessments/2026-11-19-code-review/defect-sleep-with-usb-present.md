---
type: Defect
title: Unit can enter STOP while USB power is present
description: USB wake is rising-edge only and enterStopUntilWake clears the wake flag first, so an edge just before sleep is lost.
tags: [firmware,power]
status: deprecated
confidence: read from code; fixed and tested natively, then moot
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:18:47Z" }
sources:
  - resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lightning_bugs.ino
---

# Problem

`enterStopUntilWake()` sets `wakeFlag = false` before it sleeps, and the only USB wake source is a rising edge on PF0. An edge that arrives between the decision to sleep and that line is lost. A latch at or below the 3.4 V floor with USB already present also gives no edge.

# Failure

The unit sleeps in STOP while a charger is connected and does not notice charging until the next edge (unplug and replug, or the slide switch).

# Fix

Check `lbUsbPresent()` just before entering STOP, and skip the sleep when it is high.

# Status

**Deprecated.** The lost edge was fixed (`sleepLowBattery()` counted a USB level that rose after the decision to sleep as the wake;
a test failed without it), and then the whole low-battery sleep was shelved, so the code this note is about no longer exists. It is
in commit `dda8ca5`. If that design is revived: a unit latched at or below the 3.4 V floor with USB *already* present still slept and
did not notice charging until the next edge, on purpose (skipping the sleep would defeat the floor if PF0's polarity were wrong).
