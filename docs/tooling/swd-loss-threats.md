---
type: Reference
title: "What can make a unit unreachable over SWD"
description: "The five ways firmware or hardware can lose SWD access, and what the canary unit's option bytes showed."
tags: [tooling, swd, safety, recovery]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:20:00Z" }
sources:
  - id: assessment
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/swd-recovery.md
    title: SWD recovery assessment (original, kept as history)
  - id: checkpoint
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/2026-11-17-session-checkpoint.md
    title: Session checkpoint, 2026-11-17
---

The units are sealed and the slide switch does not cut MCU power, so losing SWD can mean disassembly. Most bugs
cannot do it: crashes, hard faults, infinite loops and disabled interrupts leave SWD working, because the debug
hardware runs independently of the CPU.[^assessment] SWD is lost only when firmware (or an option-byte write) does one of:

1. **Reconfigures PA13/PA14**, by `pinMode` or a raw GPIOA mode or alternate-function write.
2. **Enters a deep low-power mode** (STOP or STANDBY) without the debug-in-low-power bits set.
3. **Stops or slows the system clock**, since the debugger reads memory over the system bus.
4. **Changes option bytes or flash protection** (read protection, write protection, NRST mode). The only category that may be permanent.
5. **Damages the pins electrically.**

The register names behind this list come from general PY32F0/STM32F0 knowledge and were **not** checked against the
reference manual when the assessment was written; the memory-map facts that have been checked are in
[memory map and information pages](../references/rm-memory-map-and-info-pages.md).[^assessment]

**What the canary showed** (2026-11-17, read with `lb_flash.py options`):[^checkpoint]

- Option user word `0x0155FEAA`, **read protection level 0**, IWDG and WWDG in software mode, brown-out reset off, no write protection.
- **NRST is a plain GPIO on this unit**, so "connect under reset" is not available.
- pyocd's Puya pack sets `DBGMCU_CR = 2` (`DBG_STOP`) and `DBGEN` on every ordinary connect, and they persist until a power-on reset. A reading of those bits therefore says nothing about the stock firmware, and `options` skips that sequence for itself.
- The unit never answered SWD for hours until the wires were moved from the Pico's own debug pads to GP2/GP3 ([wiring](swd-wiring.md)); after that it answered at once.

Mitigations, and what has and has not been built, are in [SWD recovery plan](swd-recovery-plan.md).

[^assessment]: SWD recovery assessment (original, kept as history)
[^checkpoint]: Session checkpoint, 2026-11-17
