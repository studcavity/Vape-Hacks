---
okf_version: "0.3"
title: "Vape-Hacks technical documentation"
description: "Hardware, display protocol, firmware, sync and tooling facts for re-flashing Geek Bar Pulse X Jam vapes (PY32F030EK28) and the Lightning Bugs project; use it to find a pin, a protocol detail, a tool command or where a fact came from."
---

# Vape-Hacks documentation

Facts about the Geek Bar Pulse X Jam board and our firmware and tools, one topic per file.
Material copied from the upstream project folder (`PY32F030EK28 - Geek Bar Pulse X Jam/`, never edited by us)
and from the two PY32F030 PDFs carries a source reference back to where it came from.

* [Hardware](hardware/index.md) - MCU, pin map, mode switch, power and charging.
* [Display](display/index.md) - The PLS916H LED driver: SPI frame and LED layout.
* [Firmware](firmware/index.md) - What the stock firmware and the upstream custom sketch do.
* [Lightning Bugs](lightning-bugs/index.md) - Time-synced light shows: sync design, wire format, power policy, hourly resync.
* [Tooling](tooling/index.md) - SWD wiring, build and flash wrapper, tests.
* [References](references/index.md) - Source guides, including findings recorded from the datasheet and reference manual PDFs.
