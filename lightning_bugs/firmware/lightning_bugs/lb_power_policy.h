/*
 * lb_power_policy.h — when to give up and sleep to protect the cell.
 *
 * Pure logic, no hardware access (plain C, so tests/test_lb_power_policy.py can
 * compile and drive it natively). The sketch feeds it battery readings and
 * acts on what it returns; the stop-mode entry itself lives in one function
 * in lightning_bugs.ino.
 *
 * The cell has no discharge protection that we have found, and MCU VDD is the
 * cell, so the supply voltage seen through VREFINT *is* the battery voltage.
 * VREFINT is only specified to +/-6 % (1.14-1.28 V), so a "3.60 V" reading can
 * be 3.4-3.8 V. The thresholds leave room for that: the cell is not at risk
 * until about 3.0 V.
 *
 * Rules
 *   - A reading counts only when the LEDs are off (LED load sags the cell).
 *   - LB_LOW_CONFIRM consecutive readings at or below LB_LOW_MV latch "low".
 *   - Latched "low" clears only at LB_RECOVER_MV or above (charging), or while
 *     USB power is present. Between the two thresholds it stays latched.
 *   - Latching (or any wake while latched) opens a LB_WAKE_WINDOW_MS window:
 *     stay awake, no shows, SWD reachable. After it the unit sleeps again.
 *   - With USB present the unit runs normally: it is being charged.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LB_LOW_MV           3600u     // at or below this, confirmed, means "protect the cell"
#define LB_RECOVER_MV       3750u     // latched "low" is released at or above this
#define LB_FLOOR_MV         3400u     // latches even if the USB input says "charging"
#define LB_LOW_CONFIRM      3u        // consecutive readings (10 s apart) needed to latch
#define LB_WAKE_WINDOW_MS   60000u    // awake time after a wake, or after latching
#define LB_MAX_SWITCH_TOGGLES 4u      // more switch edges than this in one window = chatter

typedef struct {
    uint8_t  low_count;
    bool     latched;
    uint32_t window_end_ms;
} LbPower;

typedef enum { LB_PWR_RUN = 0, LB_PWR_WINDOW = 1, LB_PWR_SLEEP = 2 } LbPwrAction;

static inline void lbPowerInit(LbPower* p) { p->low_count = 0; p->latched = false; p->window_end_ms = 0; }

// One battery reading, taken with the LEDs dark. mv == 0 means "no valid reading".
static inline void lbPowerFeed(LbPower* p, uint32_t mv, bool usb, uint32_t now_ms) {
    if (usb && (mv == 0 || mv > LB_FLOOR_MV)) {                     // charging, and the supply says so
        p->low_count = 0; p->latched = false; return;
    }
    if (mv == 0) return;
    if (mv <= (usb ? LB_FLOOR_MV : LB_LOW_MV)) {
        if (p->low_count < 255) p->low_count++;
        if (p->low_count >= LB_LOW_CONFIRM && !p->latched) {
            p->latched = true;
            p->window_end_ms = now_ms + LB_WAKE_WINDOW_MS;          // grace before the first sleep
        }
    } else {
        p->low_count = 0;
        if (mv >= LB_RECOVER_MV) p->latched = false;
    }
}

// The unit woke from sleep (switch or USB): give it a window, however it was woken.
static inline void lbPowerWoke(LbPower* p, uint32_t now_ms) { p->window_end_ms = now_ms + LB_WAKE_WINDOW_MS; }

static inline LbPwrAction lbPowerAction(const LbPower* p, uint32_t now_ms) {
    if (!p->latched) return LB_PWR_RUN;
    return ((int32_t)(p->window_end_ms - now_ms) > 0) ? LB_PWR_WINDOW : LB_PWR_SLEEP;
}
