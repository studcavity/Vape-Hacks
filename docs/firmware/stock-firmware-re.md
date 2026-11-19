---
type: Reference
title: "Stock firmware reverse engineering"
description: "What has been recovered from the OEM flash dump and where it lives: tables, addresses and the disassembly file."
tags: [firmware, reverse-engineering, oem]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: dump
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/backup_flash.bin
    title: OEM flash dump (backup_flash.bin)
  - id: disasm
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/backup_flash_full.s
    title: OEM disassembly (backup_flash_full.s)
---

The upstream author dumped the 64 KB OEM flash (`backup_flash.bin`) and disassembled it (`backup_flash_full.s`,
one instruction per line with its `0x0800xxxx` address). They used it to recover GPIO setup, the SPI protocol,
the animations and the battery table.[^upstream-notes] Both files are read-only reference here.

Addresses of what was recovered:

| Item | Flash address | Used in |
|---|---|---|
| Battery percentage thresholds (20 × uint16, mV) | `0x08007850` (confirmed against the dump)[^dump] | [Battery](battery-measurement.md) |
| Watt/level bar groups (ten groups, `0xFF`-terminated) | `0x0800764B` | [LED layout](../display/led-frame-layout.md) |
| Outer-ring sweep order (about 50 LEDs) | `0x08007700` | [LED layout](../display/led-frame-layout.md) |
| SPI header, tail, checksum | in code, not found as literals by us | [SPI frame](../display/pls916h-spi-protocol.md) |

The notes write the table addresses as offsets (`0x764B`, `0x7700`); flash starts at `0x08000000`, so add that
base. We have only re-checked the battery table ourselves.[^upstream-notes]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^dump]: OEM flash dump (backup_flash.bin)
[^disasm]: OEM disassembly (backup_flash_full.s)
