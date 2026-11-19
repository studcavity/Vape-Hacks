---
type: Datasheet Finding
title: "PY32F030 memory map and information pages"
description: "Address ranges of flash, SRAM, system memory, UID, option bytes and factory config, plus the UID layout and the factory temperature-sensor and HSI trim words."
tags: [pdf, reference-manual, memory-map, uid, option-bytes, factory-config]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: rm
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030%20Reference%20manual%20v1.3_EN.pdf
    title: PY32F030 Reference Manual v1.3 (EN), 442 pages
---

Read directly from the reference manual (v1.3) on 2026-11-19. Page numbers are the PDF page, which equals the
printed `n/442` footer.

**Memory map** (section 3, Table 3-1, pages 21 to 22):[^rm]

| Range | Size | Area |
|---|---|---|
| `0x0800 0000` to `0x0800 FFFF` | 64 KB | Main flash |
| `0x1FFF 0000` to `0x1FFF 0DFF` | 3.5 KB | System memory (boot loader) |
| `0x1FFF 0E00` to `0x1FFF 0E7F` | 128 B | UID |
| `0x1FFF 0E80` to `0x1FFF 0EFF` | 128 B | Option bytes |
| `0x1FFF 0F00` to `0x1FFF 0F7F` | 128 B | Factory config (HSI trim values, flash timing) |
| `0x2000 0000` to `0x2000 1FFF` | 8 KB | SRAM |

Address 0 aliases main flash, system memory or SRAM depending on the boot configuration. Apart from the UID
page, the reserved information-area spaces cannot be written and read as 0 with a response error (Table 3-1 note 1).[^rm]

**Unique ID** (section 4.3, page 30): base `0x1FFF 0E00`, 16 bytes used. Bytes 0 to 3 and 5 to 7 are the lot number as ASCII, byte 4
the wafer number, bytes 9 to 11 the X and Y die coordinates (byte 11 holds the high bits of both), and bytes 8 and 12 to 15 are
internal coding (the table shows `0x78` for byte 12). It can be read as bytes, half-words or
words. This is what the Lightning Bugs firmware copies into its [sync block](../lightning-bugs/wire-format-and-compat.md) as the device ID.[^rm]

**Factory config words** (section 4.5, Table 4-4, pages 34 to 35), all read-only, one word each:[^rm]

| Address | Content |
|---|---|
| `0x1FFF 0F00` | HSI 4 MHz selection and trim |
| `0x1FFF 0F04` | HSI 8 MHz |
| `0x1FFF 0F08` | HSI 16 MHz |
| `0x1FFF 0F0C` | HSI 22.12 MHz |
| `0x1FFF 0F10` | HSI 24 MHz |
| `0x1FFF 0F14` | `TS_CAL1`, temperature sensor at 30 °C |
| `0x1FFF 0F18` | `TS_CAL2`, temperature sensor at 85 °C |
| `0x1FFF 0F1C` onward | flash timing register values per HSI frequency |

The two `TS_CAL` words are what the firmware's die-temperature reading is calibrated against; see
[Temperature sensor](ds-temperature-sensor.md) for the sensor's own characteristics.

Not yet read: option-byte bit layout (section 4.4), flash-protection and RDP behaviour, debug-in-low-power bits
(`DBGMCU`). The [SWD recovery assessment](../../lightning_bugs/assessments/swd-recovery.md) lists these as
still unverified.

[^rm]: PY32F030 Reference Manual v1.3 (EN), 442 pages
