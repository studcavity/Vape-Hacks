---
type: Policy
title: "Lightning Bugs sleep and battery policy"
description: "The firmware sleeps only when the slide switch is at its off pole and has no automatic low-battery protection; the shelved low-battery design is kept here."
tags: [lightning-bugs, battery, sleep, policy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:24:28Z" }
sources:
  - id: header
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/firmware/lightning_bugs/lb_switch.h
    title: lb_switch.h (pure C switch logic)
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

No discharge protection has been found on the cell, and the MCU's supply is the cell.[^lb-readme] The firmware does not
protect it. Charge the unit and switch it off when it is put away.

**Switch-off sleep.** Moving the slide switch to its off pole puts the unit into STOP at once (about 6 µA per the datasheet).
The off pole is PA2 at GND, ADC below 20 counts (`LB_SWITCH_OFF_ADC`), held for 4 samples 5 ms apart
(`LB_SWITCH_OFF_CONFIRM`).[^header] That is the stock firmware's "sleep" position (position 1, left); see
[Three-position mode switch](../hardware/mode-switch.md). The mapping comes from upstream's code and notes, **not from a
measurement on this board**; confirm it on the canary.

- Any edge on PA2 wakes the unit, which goes back to sleep if the switch is still at the off pole.
- STOP freezes `millis()`, so a woken unit is **unsynced** and needs a full `sync`.
- Booting with the switch off sleeps after the 3 s boot guard.
- SWD is unreachable while the unit sleeps; moving the switch off the pole wakes it.
- PF0 (USB) no longer wakes the unit and no longer affects any decision. It is still read and reported by `status`; its
  polarity is unconfirmed (see [pin map](../hardware/pin-map.md)).
- `power_state` bit 0 (low-battery latched) stays in the wire format but is always 0.

## Shelved: automatic low-battery sleep

Built, tested natively and then removed, to avoid the ambiguity it depended on (PF0's polarity, STOP wake behaviour on a
sealed unit) and to simplify code and tests. The last commit that has it is `dda8ca5`; `lb_power_policy.h` and
`tests/test_lb_power_policy.py` are in that tree.

| Constant | Value | Meaning |
|---|---|---|
| `LB_LOW_MV` | 3600 mV | at or below this, confirmed, counts as low |
| `LB_LOW_CONFIRM` | 3 readings | consecutive, 10 s apart, LEDs dark |
| `LB_RECOVER_MV` | 3750 mV | a latched "low" clears at or above this |
| `LB_FLOOR_MV` | 3400 mV | latches even if USB says charging |
| `LB_WAKE_WINDOW_MS` | 60 000 | awake time after latching or any wake, SWD reachable |
| `LB_MAX_SWITCH_TOGGLES` | 4 | more edges than this in a window is treated as a chattering switch |

The design: readings count only with the LEDs off; three low readings latch; a latched unit blinks, stays awake for the
window, then sleeps in STOP, waking on a switch move or a PF0 rise; USB present above the floor runs normally. Before
reviving it, settle PF0's polarity on the canary and see the defect note
[sleep with USB present](../../lightning_bugs/assessments/2026-11-19-code-review/defect-sleep-with-usb-present.md) (the lost
wake edge was fixed there).

**Vrefint range.** The firmware comment and README used to say "±6 % (1.14 to 1.28 V)", copied from the upstream
notes. They now use the datasheet's 1.17 to 1.23 V (about ±2.5 %; [Vrefint](../references/ds-vrefint.md)), so a 3.60 V
reading means 3.5 to 3.7 V. This matters for `report`'s days-to-3.60 V estimate.

[^header]: lb_switch.h (pure C switch logic)
[^lb-readme]: Lightning Bugs README
