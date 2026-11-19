---
type: Design
title: "Lightning Bugs sync design"
description: "How devices share a time base over SWD: the RAM sync block, anchor, rate correction and beat grid, and what accuracy to expect."
tags: [lightning-bugs, sync, timing, swd]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

Goal: several Pulse X Jam units flash in time with one another, from a shared clock set over SWD from a
computer.[^lb-readme] The MCU can accept external signals (pin interrupts, timer capture), but the board offers
no wired or wireless link besides SWD, and its only clock is an RC oscillator that drifts. So the design is "set
the clock once, correct it often".[^lb-readme]

**How it works**

1. The firmware keeps a small *sync block* in RAM, tagged with a magic number. The host tool attaches over SWD without halting or resetting, with `auto_unlock` off so it can never mass-erase, and reads and writes it while the core runs.
2. `sync` reads the chip's `millis()` counter (`uwTick`) every 5 s for 10 min, each sample the fastest of 8 reads at the round-trip midpoint, and fits a least-squares line for the chip's rate.
3. The host writes an **anchor** (local tick to Unix µs), a **rate correction** in ppb and the **beat grid** (epoch and period).
4. The firmware computes master time as `master_us = anchor_us + L*1000 + L*corr_ppb/1e6` with `L = millis() - anchor_tick`, the same integer formula the host uses to check it.
5. Effects wait on absolute beat times (`lbWaitUntil(lbBeatTime(n))`), never chained `delay()`s. Beat `n` falls at `epoch + n × period`, so devices synced one at a time against an NTP-disciplined computer share one timeline.

**Accuracy.** Calibration removes the oscillator's fixed error; what remains is how it changes with temperature and
supply. Estimates (not measured on this chip as of the README): a few °C can cost tens to hundreds of ppm, a sagging
battery tens of ppm. Over 4 to 6 h "within a fraction of a second" is plausible if temperature is stable, not if units sit in different places.
Next steps if drift is too large: calibrate under real conditions, add a periodic resync input (IR or light sensor), or fit a 32.768 kHz crystal.[^lb-readme]

**Safety.** `lbBootGuard()` parks the firmware 3 s at power-up (a single halo LED spins). Anything that could cut off
SWD must run after it; see [what can lose SWD](../tooling/swd-loss-threats.md). Hourly operation is in
[Hourly resync](hourly-resync-and-log.md); layout of the sync block is in [Wire format](wire-format-and-compat.md).

Status in the README: compiled and tested against a simulated device; **not yet run on hardware**.[^lb-readme]

[^lb-readme]: Lightning Bugs README
