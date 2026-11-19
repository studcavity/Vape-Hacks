---
type: Plan
title: "SWD recovery plan and what is built"
description: "Planned mitigations for losing SWD (watchdog, self-healing check, forced reset, canary process) with which parts exist today."
tags: [tooling, swd, safety, recovery, plan]
status: draft
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:20:00Z" }
sources:
  - id: assessment
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/swd-recovery.md
    title: SWD recovery assessment (original, kept as history)
  - id: checkpoint
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/2026-11-17-session-checkpoint.md
    title: Session checkpoint, 2026-11-17
  - id: review
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/2026-11-19-code-review/overview.md
    title: Code review overview, 2026-11-19
---

Marked `draft`: it is a plan, partly built, with unverified register details. Threats are in
[what can lose SWD](swd-loss-threats.md).

**Process safeguards (built).** `lb_flash.py` scans source and binary for risky patterns, refuses a sealed flash
without a canary record, re-attaches three times after flashing and now checks the running build matches the
flashed one ([build and flash](build-and-flash.md)).[^review] The boot guard (`lbBootGuard`) parks the firmware for 3 s at power-up so a unit can be caught with `hold --wait`.[^assessment]

**Firmware mitigations (not built).** The assessment proposed a self-healing `lbSwdGuard()`, an independent
watchdog reset only from that guard, and a button hold of about 8 s to force a reset into the boot guard.[^assessment]
As of 2026-11-19 the firmware sources contain neither `IWDG` nor `lbSwdGuard`, yet the firmware does use STOP mode
(with `lb-allow-swd-risk` waivers); the code review calls this out as the main open decision: build the safety net or drop STOP.[^review]

**Hardware ideas.**

- **Wire NRST to a spare USB-C pin:** the assessment's best single fix, but the canary shows NRST is a GPIO, so it does not apply as proposed.[^checkpoint]
- A reed switch in the battery lead to cut power without disassembly; or let the battery run flat so the chip boots fresh (slow).
- Keep series resistors on the probe lines; the removed CC resistors let a USB-C charger pull the SWD pins toward 5 V (microamps, low risk).[^assessment]

**Still to do** (from the assessment's status list; none verified done): check register details against the reference manual,
set up and use a canary through a full run, and decide on the firmware mitigations.[^assessment]

[^assessment]: SWD recovery assessment (original, kept as history)
[^checkpoint]: Session checkpoint, 2026-11-17
[^review]: Code review overview, 2026-11-19
