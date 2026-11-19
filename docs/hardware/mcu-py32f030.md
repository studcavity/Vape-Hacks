---
type: Hardware Component
title: "PY32F030EK28 microcontroller"
description: "The Puya Cortex-M0+ MCU in the Geek Bar Pulse X Jam: memory map, clocks, ADC and what it lacks."
tags: [hardware, mcu, py32]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
  - id: rm
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030%20Reference%20manual%20v1.3_EN.pdf
    title: PY32F030 Reference Manual v1.3
---

The board's only processor is a Puya PY32F030EK28: an ARM Cortex-M0+ with 64 KB of flash at `0x08000000`
and 8 KB of RAM at `0x20000000`, a 12-bit ADC and an internal voltage reference (Vrefint).[^upstream-notes]
Flash and RAM sizes match the reference manual's memory map (64 KB main flash, 8 KB SRAM).[^rm]
The full memory map, including the unique-ID, option-byte and factory-config pages, is in
[PY32F030 memory map and information pages](../references/rm-memory-map-and-info-pages.md).

Things that shape what firmware can do:

- **Clock.** Timers and `millis()` run from the internal 24 MHz RC oscillator (HSI). There is almost certainly no
  32.768 kHz crystal on this board, so timekeeping drifts; see [Sync design](../lightning-bugs/sync-design.md).[^lb-readme]
- **No USB peripheral.** The USB-C port cannot act as a serial device. Only SWD is routed to it, on the CC pins;
  see [SWD wiring](../tooling/swd-wiring.md).[^lb-readme]
- **Toolchain.** Arduino IDE or `arduino-cli` with the py32duino core (generic PY32F030 variant); see
  [Build and flash](../tooling/build-and-flash.md).[^upstream-notes]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^lb-readme]: Lightning Bugs README
[^rm]: PY32F030 Reference Manual v1.3
