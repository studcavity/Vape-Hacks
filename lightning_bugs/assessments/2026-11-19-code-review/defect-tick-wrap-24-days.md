---
type: Defect
title: Show timing breaks after 24.8 days without a visit
description: lbMasterUs uses a signed 32-bit millisecond offset, so master time jumps back 2^32 ms after 24.8 days.
tags: [firmware,timing]
confidence: read from code; re-read on 2026-11-19 and still present
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:18:47Z" }
sources:
  - resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lb_sync.h
---

# Problem

`lbMasterUs()` computes `L = (int32_t)(millis() - anchor_tick)`. That is valid for about ±24.8 days; the comment says so. After 24.8 days since the last sync, `L` goes negative and master time jumps back by 2^32 ms (49.7 days).

# Failure

Nothing signals it. With a 3600 s period every show moves by 2^32 ms mod 3600 s = about 167 s. The host still reports the unit as synced until 49.7 days, so `status` looks fine while the shows are wrong.

# Fix options

- Re-anchor in firmware every few days (advance `anchor_tick` and `anchor_us` together).
- Count `millis()` wraps and keep a 64-bit millisecond counter.
- Document a maximum interval between visits, and have `status` warn beyond about 20 days.

# Status

**Open.** Re-checked against the code on 2026-11-19: not fixed.
