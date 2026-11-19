---
type: Reference
title: "Power and charging"
description: "How the board is powered from the LiPo cell, what the charge and USB-sense pins report, and the missing protection circuit."
tags: [hardware, power, battery]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
status: draft
sources:
  - id: upstream-notes
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/project_geekbar_pls916h.md
    title: Upstream project context notes (project_geekbar_pls916h.md)
  - id: upstream-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/PY32F030EK28%20-%20Geek%20Bar%20Pulse%20X%20Jam/README.md
    title: Upstream project README
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

The MCU's supply (VDD, and so VDDA) is wired directly to the LiPo cell, so the cell voltage can be inferred by
measuring Vrefint against VDDA.[^upstream-notes] Cell voltage is about 4.2 V full, and about 5 V on the rails
while USB is plugged in.[^upstream-readme]

- **Charger.** The upstream README names an LP4068 charge IC and notes the board seems to have two charging ICs; the author did not trace this fully.[^upstream-readme]
- **Charge/USB sense pins.** PB5 (low = charging) and PF0 (high = USB present) are described in the notes but are marked uncertain in the README. See [Pin map](pin-map.md).[^upstream-notes]
- **No cell protection found.** Lightning Bugs treats the cell as unprotected and makes the firmware enforce its own low-battery cutoff; see [power policy](../lightning-bugs/power-policy.md).[^lb-readme]
- **The slide switch does not cut MCU power.** Removing power (to reset a unit that has lost SWD) means disconnecting the battery.[^lb-readme]

[^upstream-notes]: Upstream project context notes (project_geekbar_pls916h.md)
[^upstream-readme]: Upstream project README
[^lb-readme]: Lightning Bugs README
