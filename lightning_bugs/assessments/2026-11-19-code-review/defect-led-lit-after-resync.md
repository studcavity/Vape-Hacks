---
type: Defect
title: LEDs can stay lit after a mid-show resync
description: playShow returns false without blanking; if the new grid is between shows, the driver stays powered with the last frame showing.
tags: [firmware,battery]
status: draft
confidence: read from code
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../firmware/lightning_bugs/lightning_bugs.ino
---

# Problem

`playShow()` returns `false` when the host writes a new sync mid-show, and `loop()` then skips `ledsDark()` so a continuing show does not flicker. If the new grid puts the unit between shows, `loop()` goes into `lbWaitUntil(start - 100 ms)` with the LED driver still powered and the last frame displayed.

# Failure

The LEDs stay lit on a frozen frame until 100 ms before the next show, up to an hour with an hourly grid. That wastes battery, and battery readings taken then are under LED load, which the power policy says must not count.

# Fix

Remember that the last show ended without blanking, and blank before waiting. Do not call `ledsDark()` unconditionally: that would clock bits into a driver whose power is cut.
