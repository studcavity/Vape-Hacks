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

**Measured on the canary** ([orange fucking fab](../tooling/unit-orange-fab.md), 2026-11-19, a diagnostic build that sampled PA2 and PA3 and
counted edge interrupts; the log was read over SWD while the switch was moved):

| Position (the user's name; upstream's name) | PA2 ADC | PA2 digital level | Spurious edges from our own analog-to-digital flip |
|---|---|---|---|
| off (position 1, left in upstream's notes) | 0 to 1 | low | none |
| middle (position 2) | 4093 to 4094 (VDDA) | high | about 2 per sample |
| on (position 3) | 372, 532, 882 and 93 to 373 at one boot: not stable | low | none seen |

- The three bands match upstream's (below 20, above 2000, in between). **"On" is the mid-rail band, the unstable one**, and the middle position is VDDA. An earlier version of this note had "on" and "middle" the wrong way round; the user corrected it on 2026-11-19 after a log that began at "on" (372 counts), moved to "middle" (4093) and ended at "off".
- The value at "on" is not stable (it read as low as 93 in the first seconds after one boot), so treat it as "neither of the others". Whether it can fall below the 20-count off threshold is being tested.
- **PA3 did not follow the switch**: 0 counts, level low and no edges in every position.
- A real move off GND produced edge interrupts (GND to "on" gave 1 to 2, "on" to "middle" and "middle" to GND 1 each), so PA2 can be a wake source.
- With PA2 at VDDA, `analogRead` followed by `pinMode(PA2, INPUT)` raises two edges by itself. Firmware that treats every PA2 edge as a switch move must ignore edges during its own read (fixed in firmware 0.5.1, `adcBusy`).

The slide switch does **not** cut power to the MCU, so moving it is not a reset.[^lb-swd]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^upstream-readme]: Upstream project README
[^lb-swd]: Lightning Bugs README
