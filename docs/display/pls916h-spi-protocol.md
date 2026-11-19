---
type: Protocol
title: "PLS916H SPI frame"
description: "The bit-banged SPI frame (upstream says 161 bytes) that drives the PLS916H LED matrix: header, 144 LED bytes, checksum, tail."
tags: [display, spi, protocol]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: community
    resource: https://github.com/sm2013-vapehack/geekbar_pulse_x_screen_reuse
    title: sm2013-vapehack/geekbar_pulse_x_screen_reuse (community research)
---

The PLS916H LED driver is fed by software SPI on PA9 (SCK) and PA12 (MOSI), with its supply gated by PA15
(see [Pin map](../hardware/pin-map.md)). Upstream derived the frame from the OEM firmware disassembly and
cross-checked it against community research.[^upstream-notes][^community]

Settings: SPI mode 0 (CPOL 0, CPHA 0), about 1 MHz, MSB first.[^upstream-notes]

| Part | Size | Content |
|---|---|---|
| Header | 13 bytes | `5A FF 01 5A 24 21 3D 01 83 5A FF 02 5B` |
| LED data | 144 bytes | `00` = off; any non-zero = on. The driver supports 8-bit grey levels, upstream sends `FF` for on |
| Checksum | 1 byte | 8-bit sum (wrapping) of the 144 data bytes |
| Tail | 4 bytes | `5A FF 04 5D` |
| Terminator | none | after the packet, a short (about 3 µs) clock pulse at around 200 kHz, two or three edges |

Total 13 + 144 + 1 + 4 = 162 bytes by those sizes; upstream calls it a "161-byte frame". The header, data,
checksum and tail sizes above are as upstream lists them. Count them when you next implement the frame
rather than trusting either number.[^upstream-notes]

Note: the header and tail bytes do not appear as literal runs in the flash dump (`backup_flash.bin`), so they
are probably assembled from immediates in code; we have not located them in the disassembly ourselves.

The meaning of each of the 144 bytes is in [LED frame layout](led-frame-layout.md). Upstream also saw the MOSI
line reach only about 1.8 V on a scope, which worked regardless.

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^community]: sm2013-vapehack/geekbar_pulse_x_screen_reuse (community research)
