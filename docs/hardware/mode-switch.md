---
type: Reference
title: "Three-position mode switch"
description: "How the slide switch is read through PA2's ADC value, and where upstream's two descriptions of the positions disagree."
tags: [hardware, switch, adc]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
status: draft
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
  - id: lb-swd
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

The switch is a single analog input, PA2, read with the 12-bit ADC. Upstream's notes give three bands:[^upstream-notes]

| Position | PA2 level | ADC counts |
|---|---|---|
| 1 | shorted to GND | below 20 |
| 2 | at VDDA | above 2000 |
| 3 | mid-rail | 20 to 2000 |

Because position 1 pulls PA2 to ground, any voltage formula that uses PA2 reads 0 there. Upstream measures the battery from Vrefint instead; see [Battery measurement](../firmware/battery-measurement.md).[^upstream-notes]

**Disagreement to resolve.** The two upstream files name the positions differently. The context notes call them sleep (1), active animations (2) and battery display (3). The README calls them "Close" low-power with button-triggered animation and battery readout on hold (1), animation select (2) and counter (3).[^upstream-readme] The ADC bands are the same in both; verify the behaviour on a unit before relying on either naming.

The slide switch does **not** cut power to the MCU, so moving it is not a reset.[^lb-swd]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^upstream-readme]: Upstream project README
[^lb-swd]: Lightning Bugs README
