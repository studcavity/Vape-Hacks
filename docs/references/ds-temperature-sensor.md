---
type: Datasheet Finding
title: "Temperature sensor characteristics"
description: "Datasheet limits for the on-die temperature sensor: slope, 30 °C voltage, start-up and sampling time."
tags: [pdf, datasheet, adc, temperature]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: ds
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030_Datasheet_V1.8.pdf
    title: PY32F030 Datasheet V1.8, 81 pages
---

Datasheet V1.8, section 5.3.17, Table 5-27 (page 67 of 81):[^ds]

| Parameter | Min | Typ | Max | Unit |
|---|---|---|---|---|
| Linearity `TL` | - | ±1 | ±2 | °C |
| Average slope | 2.3 | 2.5 | 2.7 | mV/°C |
| Voltage at 30 °C (±5 °C) | 0.742 | 0.76 | 0.785 | V |
| Start-up time (continuous mode) | - | 70 | 120 | µs |
| ADC sampling time needed | 9 | - | - | µs |

The slope and linearity are "guaranteed by design, not tested in production", so a per-chip two-point calibration
is worth using: the factory stores readings at 30 °C and 85 °C in `TS_CAL1` / `TS_CAL2` (see
[memory map and information pages](rm-memory-map-and-info-pages.md)). The Lightning Bugs firmware reads this sensor to record temperature
beside each clock-rate measurement ([hourly resync](../lightning-bugs/hourly-resync-and-log.md)).
