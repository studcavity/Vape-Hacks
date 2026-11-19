---
type: Reference
title: "Upstream project and prior art"
description: "The original project folder, what it contains, the rule never to edit it, and the community sources it builds on."
tags: [references, upstream, credits]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
  - id: claude-md
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/CLAUDE.md
    title: Repository CLAUDE.md
---

This repository is a fork of `SwiggityCricket/Vape-Hacks`. The folder `PY32F030EK28 - Geek Bar Pulse X Jam/` is
their work and **is never modified here**; we read it and copy facts into `docs/` with a reference.[^claude-md]
It holds a README, `project_geekbar_pls916h.md` (their working notes), the Arduino sketch and `matrix_map.h`,
the OEM flash dump and disassembly, and the two PDFs.

Sources the upstream README credits:[^upstream-readme]

- r/streetlithium and the r/hardwarehacking "Geek Bar Pulse X screen reverse engineered" thread
- `sm2013-vapehack/geekbar_pulse_x_screen_reuse` (display protocol)
- `py32duino/Arduino-PY32` (the Arduino core), and `TDLOGY/py32f0-template-project`
- `grahamwhaley/py32c642_vape`, covered in [PY32C642 prior art](py32c642-prior-art.md)
- Datasheet and reference manual from `download.py32.org`, stored in the folder as the two PDFs

[^upstream-readme]: Upstream project README
[^claude-md]: Repository CLAUDE.md
