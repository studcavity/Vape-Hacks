---
type: Reference
title: "Pin map"
description: "Which MCU pin does what on the Pulse X Jam board, with confidence noted for each."
tags: [hardware, pins]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
status: draft
sources:
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
---

Pin assignments traced from the PCB and the OEM firmware by the upstream author. Marked `draft` because the
two upstream files disagree on some pins and the author flags several as unconfirmed; none has been checked on
our own unit yet.

| Pin | Function | Confidence |
|---|---|---|
| PA2 | Analog input from the 3-position mode switch (see [Mode switch](mode-switch.md))[^upstream-readme] | traced |
| PA9 | SCK (clock) of the bit-banged SPI to the LED driver; the README labels it "SCL"[^upstream-notes] | traced |
| PA12 | MOSI of that SPI (see [PLS916H protocol](../display/pls916h-spi-protocol.md))[^upstream-readme] | traced |
| PA13 | SWDIO, routed to USB-C pin A5[^upstream-readme] | working for upstream |
| PA14 | SWCLK, routed to USB-C pin B5[^upstream-readme] | working for upstream |
| PA15 | LED driver power enable; PNP high-side switch, active **low**[^upstream-notes] | traced |
| PB1 | Originally a heater on/off control; upstream reuses it as a button input with a falling-edge interrupt[^upstream-readme] | traced |
| PF0 | USB present, high = USB power[^upstream-notes] | README says "(?)" |
| PB5 | Charge in progress, open-drain, low = charging (LP4068 CHRG pin)[^upstream-notes] | README says "(?)" |

The upstream author left other pins (microphone for inhale sensing, heater controls) unexplored.[^upstream-readme]
See [Power and charging](power-and-charging.md) for the charge/USB pins and
[Lightning Bugs power policy](../lightning-bugs/power-policy.md) for why PF0 must be verified on the canary first.

[^upstream-readme]: Upstream project README
[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
