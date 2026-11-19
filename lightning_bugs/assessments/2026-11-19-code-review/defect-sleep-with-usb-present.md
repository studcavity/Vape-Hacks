---
type: Defect
title: Unit can enter STOP while USB power is present
description: USB wake is rising-edge only and enterStopUntilWake clears the wake flag first, so an edge just before sleep is lost.
tags: [firmware,power]
confidence: read from code; re-read on 2026-11-19 and still present
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

**Open.** Re-checked against the code on 2026-11-19: not fixed.
