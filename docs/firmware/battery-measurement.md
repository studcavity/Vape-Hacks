---
type: Procedure
title: "Battery voltage and percentage"
description: "How firmware infers cell voltage from Vrefint, the per-chip calibration issue, and the OEM percentage table."
tags: [firmware, battery, adc, calibration]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: dump
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/backup_flash.bin
    title: OEM flash dump (backup_flash.bin)
  - id: ds
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030_Datasheet_V1.8.pdf
    title: PY32F030 Datasheet V1.8
---

Because the MCU runs straight off the cell, firmware reads the internal reference (Vrefint) with the ADC, which
is measured against VDDA, and inverts it:[^upstream-notes]

```
Vbattery_mV = VREFINT_MV * 4095 / rawVref        (VREFINT_MV = 1200 nominal)
```

**Calibration.** The nominal 1200 mV is only typical. Upstream's notes say a chip whose real Vrefint is 1.14 V
shows about 5 % too much (4.2 V displayed for roughly 4.0 V).[^upstream-notes] The datasheet gives a narrower
range, 1.17 to 1.23 V with a 1.2 V typical, which bounds the error at about ±2.5 % for an in-spec chip; see
[Vrefint in the datasheet](../references/ds-vrefint.md).[^ds] So a 5 % error suggests the constant, the
settling time or a reading mistake, not just normal chip variation. Per-chip procedure from upstream:

1. Measure the real cell voltage with a multimeter.
2. Get `rawVref` (back-calculate from the displayed value if needed).
3. `actual_vrefint_mV = rawVref * measured_mV / 4095`, then replace 1200 everywhere.

Do not use PA2 for this: in switch position 1 it is shorted to ground ([mode switch](../hardware/mode-switch.md)).

**Percentage table.** The OEM firmware holds a 20-entry table of millivolt thresholds in 5 % steps at flash
`0x08007850`, from 3507 mV (0 %) to 4075 mV (95 %); above the last entry the reading is 100 %. We read the
dump and confirmed these values (3507, 3587, 3619, 3643, 3661, 3675, 3687, 3697, 3709, 3721, 3746, 3766, 3793,
3822, 3852, 3882, 3912, 3972, 4012, 4075).[^dump] Upstream smooths the reading with an exponential moving average
so noise does not toggle a threshold.[^upstream-notes]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^dump]: OEM flash dump (backup_flash.bin)
[^ds]: PY32F030 Datasheet V1.8
