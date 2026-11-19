---
type: Policy
title: "Lightning Bugs low-battery policy"
description: "When the firmware stops showing and sleeps to protect the unprotected cell: thresholds, confirmation, wake window and USB handling."
tags: [lightning-bugs, battery, sleep, policy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:24:28Z" }
sources:
  - id: header
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lb_power_policy.h
    title: lb_power_policy.h (pure C policy logic)
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

No discharge protection has been found on the cell, and the MCU's supply is the cell, so the firmware protects
it itself.[^lb-readme] The rules are plain C in `lb_power_policy.h` so they can be compiled and tested natively.[^header]

| Constant | Value | Meaning |
|---|---|---|
| `LB_LOW_MV` | 3600 mV | at or below this, confirmed, counts as low |
| `LB_LOW_CONFIRM` | 3 readings | consecutive, 10 s apart, LEDs dark |
| `LB_RECOVER_MV` | 3750 mV | a latched "low" clears at or above this |
| `LB_FLOOR_MV` | 3400 mV | latches even if USB says charging |
| `LB_WAKE_WINDOW_MS` | 60 000 | awake time after latching or any wake, SWD reachable |
| `LB_MAX_SWITCH_TOGGLES` | 4 | more edges than this in a window is treated as a chattering switch |

Behaviour:[^lb-readme]

- A reading counts only with the LEDs off, since LED load sags the cell.
- Once latched, the unit stops showing, flashes the centre cluster three times, stays awake for the window, then sleeps in STOP mode (about 6 µA per the datasheet).
- It wakes on a switch move (PA2) or USB appearing (PF0 rising). Each wake opens another window; one window costs about 7 µAh.
- With USB present and supply above 3400 mV it runs normally. Below that it sleeps regardless, which also covers a wrong guess about PF0's polarity.
- STOP freezes `millis()`, so a unit that has slept is **unsynced** and needs a full `sync` after charging.

**Switch-off sleep.** Separately from the battery rules, moving the slide switch to its off pole puts the unit into
STOP at once: no window, no show, whatever the battery or USB say. The off pole is PA2 at GND, ADC below 20 counts
(`LB_SWITCH_OFF_ADC`), held for 4 samples 5 ms apart (`LB_SWITCH_OFF_CONFIRM`). That is the stock firmware's "sleep" position
(position 1, left); see [Three-position mode switch](../hardware/mode-switch.md). The mapping comes from upstream's code and
notes, **not from a measurement on this board**; confirm it on the canary. Any edge on PA2 wakes the unit, which goes
back to sleep if the switch is still at the off pole. Waking leaves it unsynced, as after any STOP. Boot with the switch off
sleeps after the 3 s boot guard.[^header]

**Vrefint range.** The firmware comment and README used to say "±6 % (1.14 to 1.28 V)", copied from the upstream
notes. They now use the datasheet's 1.17 to 1.23 V (about ±2.5 %; [Vrefint](../references/ds-vrefint.md)), so a 3.60 V reading
means 3.5 to 3.7 V. The thresholds were not changed, since they are conservative either way. The README's pre-flash
checks on the canary (USB input follows plugging) apply to PF0 in the [pin map](../hardware/pin-map.md).

[^header]: lb_power_policy.h (pure C policy logic)
[^lb-readme]: Lightning Bugs README
