---
type: Risk
title: Hardware and firmware risks that need a unit to settle
description: Unverified assumptions in the firmware, namely power use, STOP wake-up, debug bits, sensors, LED driver, watchdog.
tags: [firmware,hardware,power]
status: draft
confidence: unverified
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../firmware/lightning_bugs/lightning_bugs.ino
  - resource: ../../firmware/lightning_bugs/lb_sync.h
  - resource: ../2026-11-17-session-checkpoint.md
  - resource: ../swd-recovery.md
---

# Debug bits survive resets

The checkpoint doc says pyocd's `DebugCoreStart` sets `DBG_STOP` on every ordinary connection (`dump`, `lb_sync`, `flash`), and the bit persists until power-on reset. After the hourly `resync` visit, STOP mode may draw far more than the "~7 µAh per wake" in the firmware header, which would weaken the low-battery protection exactly when it matters.

# Idle drain

Between shows the CPU sleeps with WFI and wakes every millisecond, and never enters STOP because STOP stops `millis()`. At 24 MHz that may be milliamps for hours. No document estimates battery life for the hourly design. Unsynced units flash the LEDs at full brightness for 100 ms every 2 s, forever.

# STOP wake-up

Nobody has confirmed that the clock and `millis()` rate are unchanged after a STOP wake. If the HSI setting changes, every wake silently skews timing.

# Unverified chip assumptions

- `analogRead(ATEMP)` and `analogRead(AVREF)` return sensible counts.
- The battery voltage derived from a nominal 1.2 V VREFINT is accurate (the header admits ±6 %).
- `TS_CAL1` and `TS_CAL2` sit at the cited addresses.
- `uwTick` is the counter behind `millis()`.
- The LED driver accepts a frame immediately after `ledPower(true)` in `unsyncedBlink`, `lowBatteryBlink` and the mid-show join. Only the pre-show path has `LED_WAKE_LEAD_MS`.

# No watchdog

A hang in the field stays hung. NRST is a GPIO, so nothing external can reset the chip either.

# Host clock

Nothing checks that the computer's clock is NTP-synced. Devices synced from different machines inherit each machine's error.
