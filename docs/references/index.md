# References

* [Reading the two PDFs](pdf-sources.md) - How to search the PY32F030 datasheet and reference manual without reading them whole, and which of our docs came from them.
* [Upstream project and prior art](upstream-project.md) - The original project folder, what it contains, the rule never to edit it, and the community sources it builds on.
* [Prior art: PY32C642 in a Hayati Pro Ultra](py32c642-prior-art.md) - What another author learned probing a similar Puya vape over SWD from a Pico, and which of it may apply to us.

## PDF findings

* [PY32F030 memory map and information pages](rm-memory-map-and-info-pages.md) - Address ranges of flash, SRAM, system memory, UID, option bytes and factory config, plus the UID layout and the factory temperature-sensor and HSI trim words.
* [Internal reference voltage (Vrefint) in the datasheet](ds-vrefint.md) - Datasheet limits for Vrefint: 1.17 to 1.23 V, 1.2 V typical, up to 100 ppm/°C; narrower than upstream's quoted range.
* [Temperature sensor characteristics](ds-temperature-sensor.md) - Datasheet limits for the on-die temperature sensor: slope, 30 °C voltage, start-up and sampling time.
