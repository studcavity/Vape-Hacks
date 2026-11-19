/*
 * lb_switch.h — the slide switch's "off" pole.
 *
 * Pure logic, no hardware access (plain C, so tests/test_lb_switch.py can compile it natively).
 * Moving the switch to this pole puts the unit into STOP; see sleepSwitchOff() in lightning_bugs.ino.
 *
 * Upstream reads PA2 with the ADC: position 1 (left) shorts it to GND, below 20 counts of 4095, and the
 * stock firmware treats that position as sleep. Anything else (VDDA above 2000, or mid-rail) is "on".
 * Taken from upstream's code and notes, not measured on this board: see docs/hardware/mode-switch.md.
 * A reading must hold for LB_SWITCH_OFF_CONFIRM samples before it counts.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LB_SWITCH_OFF_ADC     20u     // PA2 ADC counts below this = switch at the off pole
#define LB_SWITCH_OFF_CONFIRM 4u      // consecutive samples (5 ms apart) at the off pole

static inline bool lbSwitchIsOff(uint32_t adc) { return adc < LB_SWITCH_OFF_ADC; }
