---
type: Reference
title: "LED frame layout"
description: "What each of the 144 LED bytes controls: seven-segment digits, halo ring, icons, outer ring, bar levels and column LEDs."
tags: [display, leds, layout]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: matrix-map
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030EK28/matrix_map.h
    title: Upstream matrix_map.h (LED index tables)
---

Byte indices into the 144-byte LED block of the [SPI frame](pls916h-spi-protocol.md). Upstream confirmed these
from the OEM animation and display routines.[^upstream-notes] The index tables themselves are in `matrix_map.h`
(also copied into our `lightning_bugs/firmware/lightning_bugs/matrix_map.h`).[^matrix-map]

**Digits.** Segment order per digit: A top, B upper right, C lower right, D bottom, E lower left, F upper left, G middle.

| Digit | Bytes | Role |
|---|---|---|
| 2 | 0 to 6 | top row, tens |
| 3 | 8 to 14 | top row, ones |
| 4 | 16 to 22 | bottom row, tens |
| 5 | 24 to 30 | bottom row, ones |
| 0 | B = 7, C = 15 | top-left "1" (only segments B and C exist) |
| 1 | B = 23, C = 31 | bottom-left "1" (only B and C) |

Bytes 7, 15, 23 and 31 therefore double as icon/separator LEDs and as the partial digits' segments.

**Halo ring.** Bytes 33 to 48. `HALO_MAP` runs `33..45` clockwise (13 ring LEDs), then `48, 47, 46` for the centre cluster of three.

**Icons.** Byte 32 is the lightning bolt above the top digit row; byte 49 is the blob icon below the bottom row.

**Outer ring.** About 50 decorative LEDs, clockwise, from the OEM table at flash `0x7700` (`OUTER_SWEEP`). **Bar levels.** Ten groups from the table at `0x764B`, terminated by `0xFF` (`BAR_LEVELS[10][16]`). **Columns.** `LEFT_COL[20]` and `RIGHT_COL[20]`.

**Extra LEDs** not in the outer sweep or halo: `EXTRA_LEDS[46]` = bytes 32, 49, 50 to 61, 64, 68, 73, 77, 82, 85 to 93, 96, 98, 101, 110, 119 to 123, 128 to 131, 134 to 138. A full-display animation must light these as well as the outer sweep and halo.

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^matrix-map]: Upstream matrix_map.h (LED index tables)
