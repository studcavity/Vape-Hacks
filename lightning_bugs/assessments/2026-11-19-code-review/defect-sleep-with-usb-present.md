---
type: Defect
title: Unit can enter STOP while USB power is present
description: USB wake is rising-edge only and enterStopUntilWake clears the wake flag first, so an edge just before sleep is lost.
tags: [firmware,power]
confidence: read from code; edge-loss part fixed and tested natively, not on hardware
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

**Partly fixed** (branch `sbx/admiring-ritchie/01-switch-off-sleep`). The lost edge is fixed: `sleepLowBattery()` notes the
USB level when it decides to sleep and, after clearing `wakeFlag`, counts a USB level that has risen since then as the wake.
A test (`test_low_battery_sleep_does_not_lose_a_usb_edge_that_lands_just_before_it`) fails without that line.

**Not changed, on purpose:** a unit latched at or below the 3.4 V floor with USB *already* present still sleeps, and does not
notice charging until the next edge. The note's "skip the sleep when USB is high" would defeat the floor, which is the only
protection if PF0's polarity was guessed wrong (see [power policy](../../../docs/lightning-bugs/power-policy.md)). The charger IC
charges the cell without the MCU. Waking on both PF0 edges would close it, at the cost of a wake window per unplug.
