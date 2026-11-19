---
type: Defect
title: Syncs are not acknowledged during the low-battery window or boot guard
description: holdWindow and lbBootGuard never call lbPoll, so a sync written then is not adopted until later.
tags: [firmware,host]
confidence: read from code; re-read on 2026-11-19 and still present
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:18:47Z" }
sources:
  - resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lightning_bugs.ino
  - resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lb_sync.h
  - resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/host/lb_sync.py
---

# Problem

**Update:** `holdWindow()` was removed with the shelved low-battery sleep; only the boot-guard part below still applies.

`holdWindow()` (60 s awake window) and `lbBootGuard()` (3 s, or while `hold` is set) never call `lbPoll()`. The host's `write_sync` waits 3 s for `ack_seq`.

# Failure

`sync` or `resync` writes its data, then fails with "firmware did not acknowledge the sync" although the data is in RAM. The firmware adopts it only once the window or guard ends, so the user sees an error and may retry needlessly.

# Fix options

Call `lbPoll()` in both loops, or have the host detect `hold` or a latched low battery and say so before sampling.

# Status

**Open.** Re-checked against the code on 2026-11-19: not fixed.
