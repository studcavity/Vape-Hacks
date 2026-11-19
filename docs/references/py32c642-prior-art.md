---
type: Reference
title: "Prior art: PY32C642 in a Hayati Pro Ultra"
description: "What another author learned probing a similar Puya vape over SWD from a Pico, and which of it may apply to us."
tags: [references, prior-art, swd, pico]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:20:00Z" }
sources:
  - id: assessment
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/py32c642-prior-art.md
    title: PY32C642 prior-art assessment (original, kept as history)
  - id: repo
    resource: https://github.com/grahamwhaley/py32c642_vape
    title: grahamwhaley/py32c642_vape
---

Everything here is that author's report as read from their README (tree `5d82bc21`), not tried on our unit. The code,
schematic and datasheets in their repo were not read.[^assessment]

**How close to us.** Same vendor, core and kind of device, and the same Pico probe idea. Different chip (PY32C642F15,
24 KB flash, 3 KB RAM, no native pyocd target, whereas ours has `py32f030x8`), different access (four labelled test points
after opening the case, not USB-C A5/B5) and different probe firmware (`free-dap`, not `debugprobe`).[^assessment]

**What they found**

1. A bare wire connection did not work with `edbg` or `pyocd`.
2. Series and pull-up resistors plus a **1 MHz** clock fixed it; values and the contribution of each change are unknown.
3. After every power-up `pyocd` could not connect until `edbg` had been run once (it reports failure, but afterwards `pyocd` works). Unexplained.
4. The flash was not read-protected, so `pyocd cmd ... savemem` could back it up.
5. Their battery was dead; they suggest powering from the probe with the battery disconnected.
6. Their units varied: corroded pads, and one drew milliamps in stop mode.

**What it may mean for us (inference).** Our tools already default to 500 kHz, below their 1 MHz; go lower if flaky.
The `edbg` step is unlikely to apply (the F030 prior art flashed with plain `pyocd flash`); treat it as a fallback. The two
projects give opposite power advice (probe-powered versus battery-powered); do not power our unit from the Pico's 3.3 V
without checking the unit's operating range and that the charger and USB-C lines are not back-driven.[^assessment]
Our own wiring is in [SWD wiring](../tooling/swd-wiring.md).

[^assessment]: PY32C642 prior-art assessment (original, kept as history)
