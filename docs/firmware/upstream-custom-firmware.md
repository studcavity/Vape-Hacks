---
type: Reference
title: "Upstream custom firmware"
description: "How the upstream PY32F030EK28 sketch is structured: frame buffers, OR-compose pitfall, button handling and modes."
tags: [firmware, upstream, arduino]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
  - id: sketch
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030EK28/PY32F030EK28.ino
    title: Upstream sketch PY32F030EK28.ino
---

The upstream project replaces the OEM firmware with an Arduino sketch (`PY32F030EK28.ino` plus `matrix_map.h`)
that shows 11 LED animations (several copied from the OEM dump), a counter mode and a battery readout.[^upstream-readme]
Our own firmware is the separate [Lightning Bugs](../lightning-bugs/index.md) sketch; this page records
the upstream design so its lessons are not lost.

- **Two frame buffers, OR-composed.** `frameDigits` and `frameHalo` (144 bytes each) are ORed into `frameOut` by
  `composeAndSend()`. If the halo buffer is all `0xFF`, digits can never turn off, so call `haloClear()` before showing digits and write full `0xFF`/`0x00` bytes per segment.[^upstream-notes]
- **Animations are interruptible.** The animation loops poll `animOK()`: no pending button edge and the switch still where it was when the animation started.[^upstream-notes]
- **Button.** Falling-edge interrupt sets a flag; release is confirmed after 50 ms of sustained high; a hold is 500 ms.[^upstream-notes]
- **Hold in position 1** wakes the display and shows battery percentage on top and volts in tenths on the bottom, then blanks on release.[^upstream-notes]
- **Delays chain.** Animations step with `delay()`, so timing error accumulates; Lightning Bugs schedules against absolute beat times instead ([sync design](../lightning-bugs/sync-design.md)).

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^upstream-readme]: Upstream project README
