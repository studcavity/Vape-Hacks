---
type: Datasheet Finding
title: "Internal reference voltage (Vrefint) in the datasheet"
description: "Datasheet limits for Vrefint: 1.17 to 1.23 V, 1.2 V typical, up to 100 ppm/°C; narrower than upstream's quoted range."
tags: [pdf, datasheet, adc, vrefint, battery]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:24:28Z" }
sources:
  - id: ds
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030_Datasheet_V1.8.pdf
    title: PY32F030 Datasheet V1.8, 81 pages
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
---

Datasheet V1.8, section 5.3.18, Table 5-28 "Built-in reference voltage characteristics" (page 67 of 81):[^ds]

| Parameter | Min | Typ | Max | Unit |
|---|---|---|---|---|
| `VREFINT` internal reference voltage | 1.17 | 1.2 | 1.23 | V |
| `tstart_vrefint` start time | - | 10 | 15 | µs |
| `Tcoeff` temperature coefficient | - | - | 100 (design, not tested) | ppm/°C |
| `Ivcc` current from VCC | - | 12 | 20 | µA |

**Discrepancy.** The upstream notes quote the spec range as 1.14 to 1.28 V.[^upstream-notes] The datasheet we
have says 1.17 to 1.23 V. Use the datasheet figure; for an in-spec chip, a fixed 1200 mV constant is therefore at most about 2.5 % off,
and 100 ppm/°C over a 40 °C swing adds only about 0.4 %. Our (now removed) `lb_power_policy.h` comment and the Lightning Bugs README repeated the upstream figure until 2026-11-19; both now state the datasheet range and note that upstream may have measured something different on their own chip. How this feeds the battery reading is in
[Battery voltage and percentage](../firmware/battery-measurement.md).
