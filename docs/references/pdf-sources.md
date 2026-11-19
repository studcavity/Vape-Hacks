---
type: Reference
title: "Reading the two PDFs"
description: "How to search the PY32F030 datasheet and reference manual without reading them whole, and which of our docs came from them."
tags: [references, pdf, how-to]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: ds
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030_Datasheet_V1.8.pdf
    title: PY32F030 Datasheet V1.8, 81 pages
  - id: rm
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/PY32F030%20Reference%20manual%20v1.3_EN.pdf
    title: PY32F030 Reference Manual v1.3 (EN), 442 pages
---

Two PDFs live in the upstream folder: the datasheet V1.8 (81 pages; electrical limits, pinout, packages) and the
reference manual v1.3 (442 pages; registers, memory map, peripherals).[^ds][^rm] They are too large to read whole.

To search them without touching the upstream folder, extract text into a scratch directory and grep it:

```sh
pdftotext -layout "<pdf>" /tmp/rm.txt      # poppler-utils; page breaks are form feeds
grep -n "UID" /tmp/rm.txt
```

Pages are separated by form feed characters, so the page of a hit is the count of form feeds before it. The manual's printed footer `n/442` equals the PDF page.

**Rule:** each time a detail is learned from a PDF, write a small `Datasheet Finding` concept in this directory
with the section, table and page, and link it from [references index](index.md). Findings so far:

- [Memory map and information pages](rm-memory-map-and-info-pages.md)
- [Vrefint](ds-vrefint.md)
- [Temperature sensor](ds-temperature-sensor.md)

[^ds]: PY32F030 Datasheet V1.8, 81 pages
[^rm]: PY32F030 Reference Manual v1.3 (EN), 442 pages
