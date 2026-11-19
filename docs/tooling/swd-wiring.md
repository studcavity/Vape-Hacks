---
type: Procedure
title: "Wiring a Pico debug probe to the unit over USB-C"
description: "How SWD reaches the MCU through the USB-C CC pins, the Pico wiring, resistors, and why the unit is unreachable while asleep."
tags: [tooling, swd, wiring, pico, pyocd]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
status: draft
sources:
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README (Debug probe and wiring section)
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
---

Marked `draft`: the README itself says this wiring is **not yet tried on our canary**. Check it with
`pyocd list` and `lb_flash.py dump` before anything else.[^lb-readme]

SWDIO (PA13) and SWCLK (PA14) are brought out to the USB-C port's A5 and B5 (the CC pins), so the case need not be opened.[^upstream-readme]

```
SWCLK: Pico GP2 (pin 4) -> ~240 ohm -> B5 -> PA14
SWDIO: Pico GP3 (pin 5) -> ~240 ohm -> A5 -> PA13
GND:   Pico GND -> USB-C A12 (B12 also GND)
```

- Upstream also pulled both lines up to 3.3 V with 10 k and removed the unit's own CC pull-downs (it recalls 2.5 k; the VapeRE schematic and another project say 5.1 k). With the pull-downs left in, the external pull-ups only divide to about 1.1 V; whether it works that way is untested here.[^lb-readme]
- If it does not connect, swap the two signal wires or flip the connector; the two sources disagree on which pin is which.[^lb-readme]
- **Do not use the three SWCLK/GND/SWDIO pads on the Pico's underside**; they are the Pico's own debug port.
- The Pico drives 3.3 V while the unit runs at battery voltage (up to about 4.2 V, 5 V on USB), hence the series resistors. Power the unit from its own battery, and do not plug a charger into the breakout while the probe is attached.
- **The unit sleeps and SWD is unavailable while it does.** The slide switch or plugging in a charger opens a short connect window; run `dump --poll` first, then move the switch.[^lb-readme]
- Probe: a Raspberry Pi Pico running debug-probe (CMSIS-DAP) firmware, USB `2e8a:000c`, via pyocd; pick it with `--probe`/`-u`. Always take a flash backup first: `python3 tools/lb_flash.py -u <probe> dump`.

Recovery planning for a unit that loses SWD is in [SWD recovery](../../lightning_bugs/assessments/swd-recovery.md); flashing in [Build and flash](build-and-flash.md).

[^lb-readme]: Lightning Bugs README (Debug probe and wiring section)
[^upstream-readme]: Upstream project README
