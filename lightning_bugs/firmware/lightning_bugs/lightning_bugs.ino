/*
 * Lightning Bugs — synchronized light show for the Geek Bar Pulse X Jam
 * (PY32F030EK28 + PLS916H LED driver).
 *
 * Every device synced with host/lb_sync.py runs the same show at the same
 * moments: one show starts on every beat of the shared grid (epoch + n * period,
 * Unix time), runs for SHOW_MS, then the LEDs go dark and the LED driver's power
 * is cut until the next one. Set the cadence with e.g.  lb_sync.py sync --every 3600
 * for a show on every UTC hour.
 *
 * The show is the "comet chase" from the stock firmware (haloCometChase in
 * ../../../PY32F030EK28 - Geek Bar Pulse X Jam/PY32F030EK28/PY32F030EK28.ino):
 * a bright dot with a two-step fading tail circles the 13-LED halo, and the
 * centre cluster breathes once per lap. Here every frame is a pure function of
 * (master time - show start), so a device that is a few ms late, or that is
 * resynced mid-show, simply draws the frame it should be on.
 *
 * Unsynced devices flash the centre cluster briefly every 2 s, so it is obvious
 * which units still need a sync. While idle the firmware also samples the die
 * temperature and keeps the chip UID in the sync block (see lb_sync.h).
 *
 * Battery protection (lb_power_policy.h): the cell has no protection circuit, so
 * once the supply stays at or below 3.60 V the unit stops showing, gives you a
 * 60 s awake window (SWD reachable), then sleeps in STOP mode until the slide
 * switch moves or USB power appears. Every wake opens another 60 s window and
 * then, if the battery is still low, sleeps again, so accidental wakes cost
 * about 7 uAh each. STOP freezes millis(), so a woken unit is unsynced and
 * needs a new `lb_sync.py sync`. With USB power present the unit runs normally.
 *
 * Switch-off sleep: moving the slide switch to its off pole (PA2 at GND, the
 * stock firmware's "sleep" position) puts the unit into STOP at once, whatever
 * the battery or USB say, and any move off that pole wakes it. A unit that has
 * slept is unsynced. See sleepSwitchOff().
 *
 * LED driver code is a trimmed copy of the stock firmware. Board: Generic
 * PY32F030 (py32duino). Flash with tools/lb_flash.py.
 */
#include <Arduino.h>
#include <string.h>
#include "matrix_map.h"
#include "lb_sync.h"

// ─── Show timing ─────────────────────────────────────────────────────────────
#define SHOW_STEP_MS   50                                  // one halo LED per step, as in the stock chase
#define SHOW_LAPS      9
#define SHOW_FRAMES    (HALO_RING_COUNT * SHOW_LAPS)       // 117 frames, 5.85 s
#define LED_WAKE_LEAD_MS 100                               // power the LED driver this long before a show

// ─── PLS916H bit-bang SPI (PA9 = SCK, PA12 = MOSI) ───────────────────────────
#define SCK_H()   GPIOA->BSRR = (1u << 9)
#define SCK_L()   GPIOA->BSRR = (1u << 25)
#define MOSI_H()  GPIOA->BSRR = (1u << 12)
#define MOSI_L()  GPIOA->BSRR = (1u << 28)

static void spiByteFast(uint8_t b) {
    for (int8_t i = 7; i >= 0; i--) {
        if ((b >> i) & 1) MOSI_H(); else MOSI_L();
        SCK_H();
        SCK_L();
    }
}

static void spiByteTerminate(uint8_t b) {
    for (int8_t i = 7; i >= 0; i--) {
        if ((b >> i) & 1) MOSI_H(); else MOSI_L();
        delayMicroseconds(2);
        SCK_H();
        delayMicroseconds(2);
        SCK_L();
        delayMicroseconds(1);
    }
}

static uint8_t frame[144];

static void sendFrame() {
    static const uint8_t header[13] = {
        0x5A,0xFF,0x01,0x5A,0x24,0x21,0x3D,0x01,0x83,0x5A,0xFF,0x02,0x5B
    };
    static const uint8_t tail[4] = {0x5A,0xFF,0x04,0x5D};
    uint8_t chk = 0;
    for (int i = 0; i < 144; i++) chk += frame[i];
    for (int i = 0; i < 13;  i++) spiByteFast(header[i]);
    for (int i = 0; i < 144; i++) spiByteFast(frame[i]);
    spiByteFast(chk);
    for (int i = 0; i < 4;   i++) spiByteFast(tail[i]);
    spiByteTerminate(0x00);
}

static inline void clearFrame() { memset(frame, 0, sizeof frame); }

// PA15 drives a PNP high-side switch for the LED driver: LOW = powered.
static void ledPower(bool on) { digitalWrite(PA15, on ? LOW : HIGH); }

// Set when a show was cut short (a resync moved the grid) and the driver was left powered, showing its last frame.
static bool ledsLeftLit = false;

static void ledsDark() {                  // blank the driver, then cut its power
    clearFrame();
    sendFrame();
    ledPower(false);
    ledsLeftLit = false;
}

// ─── Low-battery sleep ───────────────────────────────────────────────────────
// Wake sources: PF0 rising (USB power appears) and PA2 any edge (slide switch).
// The ISRs only set flags; they stay attached all the time so the toggle count
// can spot a chattering switch (PA2 is analog-biased on this board, and mid-rail
// may sit on the digital threshold).
static volatile bool    wakeFlag = false;
static volatile uint8_t switchToggles = 0;
static volatile bool    switchChanged = true;     // PA2 moved (or boot): re-read the switch before the next decision
static bool             switchIsOff = false;
static void onUsbWake()    { wakeFlag = true; }
static void onSwitchWake() { wakeFlag = true; switchChanged = true; if (switchToggles < 255) switchToggles++; }

static void attachSwitchWake() { attachInterrupt(digitalPinToInterrupt(PA2), onSwitchWake, CHANGE); }

// The ONLY place the firmware enters STOP. Returns after a wake. The caller clears
// wakeFlag first, then makes its last check, so an edge in between is not lost. STOP stops the
// HSI and SysTick; on exit the core runs from HSI again (reference manual 6.3.2).
// If this misbehaves the unit cannot be reached over SWD until it wakes: this is
// canary-first code (see assessments/swd-recovery.md).
static void enterStopUntilWake() {
    while (!wakeFlag) {
        __disable_irq();
        if (!wakeFlag) {
            PWR->CR1 |= PWR_CR1_LPR;                              // lb-allow-swd-risk: low-power regulator in STOP
            SCB->SCR |= SCB_SCR_SLEEPDEEP_Msk;                    // lb-allow-swd-risk: deep sleep
            __WFI();
            SCB->SCR &= ~SCB_SCR_SLEEPDEEP_Msk;                   // lb-allow-swd-risk: back to normal sleep
        }
        __enable_irq();                                           // a pending wake ISR runs here
    }
}

static void sleepLowBattery() {
    bool usbAtDecision = lbUsbPresent();                          // the wake edge is a rise from this level
    ledsDark();                                                   // driver blank and unpowered (PA15 high)
    bool chatter = switchToggles >= LB_MAX_SWITCH_TOGGLES;
    if (chatter) detachInterrupt(digitalPinToInterrupt(PA2));     // USB only until the next USB wake
    switchToggles = 0;
    wakeFlag = false;
    // USB appeared after the decision to sleep: the rising edge came before the line above cleared its
    // flag. Count it as the wake. (Already present at the decision, below the floor: sleep anyway; the
    // charger IC does not need the MCU, and the floor must hold if PF0's polarity was guessed wrong.)
    if (!usbAtDecision && lbUsbPresent()) wakeFlag = true;
    enterStopUntilWake();
    if (chatter) attachSwitchWake();
    lbBlock.wake_count++;
    lbBlock.ack_seq = 0;                                          // millis() stood still: the old sync is void
    lbS.synced = false;
    lbPowerWoke(&lbPower, millis());
}

// True if the slide switch has stayed at its off pole (PA2 at GND) for LB_SWITCH_OFF_CONFIRM
// samples. analogRead() puts PA2 in analog mode, where the digital edge cannot fire, so the pin is
// put back to a digital input afterwards: nothing may sleep with PA2 left analog.
static bool switchAtOffPole() {
    bool off = true;
    for (uint8_t i = 0; i < LB_SWITCH_OFF_CONFIRM && off; i++) {
        off = lbSwitchIsOff(analogRead(PA2));
        if (off) delay(5);
    }
    pinMode(PA2, INPUT);
    return off;
}

// Switch moved to the off pole: stop at once, no window and no show, whatever the battery or USB say.
// Any edge on PA2 wakes it; it sleeps again if the switch is still at the off pole. A mid-slide wake is
// cheap, so there is no chatter handling here. The unit is unsynced afterwards (STOP stops millis()).
static void sleepSwitchOff() {
    ledsDark();
    do {
        wakeFlag = false;
        if (digitalRead(PA2) != LOW) break;                       // already left GND: do not sleep on a missed edge
        enterStopUntilWake();
    } while (switchAtOffPole());
    switchIsOff = false;
    switchChanged = true;
    lbBlock.wake_count++;
    lbBlock.ack_seq = 0;
    lbS.synced = false;
    lbPowerWoke(&lbPower, millis());
}

// Three short centre-cluster flashes: "low battery, going back to sleep".
static void lowBatteryBlink() {
    ledPower(true);
    for (int i = 0; i < 3; i++) {
        clearFrame();
        for (int c = 0; c < HALO_CENTER_COUNT; c++) frame[HALO_MAP[HALO_RING_COUNT + c]] = 0xFF;
        sendFrame();
        delay(100);
        clearFrame();
        sendFrame();
        delay(150);
    }
    ledsDark();
}

// Stay awake, dark, with SWD reachable, until the window ends, USB appears, or the
// battery recovers. Readings continue (lbTempService) so a charge ends it early.
static void holdWindow() {
    static bool announced = false;
    if (!announced) { announced = true; lowBatteryBlink(); }
    while (lbPowerAction(&lbPower, millis()) == LB_PWR_WINDOW && !switchChanged) {
        lbTempService(1000000);
        __WFI();
    }
    announced = false;
}

// True if the power policy took over this pass (the caller should re-evaluate).
static bool powerGate() {
    if (switchChanged) { switchChanged = false; switchIsOff = switchAtOffPole(); }
    if (switchIsOff) { sleepSwitchOff(); return true; }
    switch (lbPowerAction(&lbPower, millis())) {
        case LB_PWR_WINDOW: holdWindow();       return true;
        case LB_PWR_SLEEP:  sleepLowBattery();  return true;
        default:                                return false;
    }
}

static bool powerOk() { return !switchChanged && lbPowerAction(&lbPower, millis()) == LB_PWR_RUN; }

// ─── Boot guard indicator: single halo LED spinning ──────────────────────────
static void guardSpinner(uint32_t elapsedMs) {
    clearFrame();
    frame[HALO_MAP[(elapsedMs / 80) % HALO_RING_COUNT]] = 0xFF;
    if (lbBlock.hold) for (int i = 0; i < HALO_CENTER_COUNT; i++) frame[HALO_MAP[HALO_RING_COUNT + i]] = 0xFF;
    sendFrame();
}

// ─── The show: comet chase around the halo ───────────────────────────────────
// Frame k = floor(t / SHOW_STEP_MS): comet head on LED (k mod 13), tails on the
// two LEDs behind it, centre cluster following the breathe table over one lap.
static void renderCometFrame(uint32_t k) {
    uint32_t i = k % HALO_RING_COUNT;
    clearFrame();
    uint8_t cb = BREATHE_TABLE[(uint8_t)(i * 256 / HALO_RING_COUNT)];
    for (int c = 0; c < HALO_CENTER_COUNT; c++) frame[HALO_MAP[HALO_RING_COUNT + c]] = cb;
    frame[HALO_MAP[i]]                                           = 0xFF;
    frame[HALO_MAP[(i + HALO_RING_COUNT - 1) % HALO_RING_COUNT]] = 0x50;
    frame[HALO_MAP[(i + HALO_RING_COUNT - 2) % HALO_RING_COUNT]] = 0x18;
}

// Play the show that started at master time startUs. Returns false, without
// blanking, if the host writes a new sync mid-show (the loop then re-reads the grid).
static uint32_t seqAtStart;
static bool sameSync() { return lbS.seq == seqAtStart && powerOk(); }

static bool playShow(int64_t startUs) {
    seqAtStart = lbS.seq;
    int64_t stepUs = (int64_t)SHOW_STEP_MS * 1000;
    int64_t elapsed = lbMasterUs() - startUs;
    uint32_t k = elapsed > 0 ? (uint32_t)(elapsed / stepUs) : 0;      // join mid-show in step
    for (; k < SHOW_FRAMES; k++) {
        if (!lbWaitUntil(startUs + (int64_t)k * stepUs, sameSync)) return false;
        // If we are already past the next frame (slow SPI, or a time jump), skip to it.
        int64_t late = lbMasterUs() - (startUs + (int64_t)k * stepUs);
        if (late > stepUs) { k += (uint32_t)(late / stepUs); if (k >= SHOW_FRAMES) break; }
        renderCometFrame(k);
        sendFrame();
    }
    return true;
}

// ─── Unsynced indicator ──────────────────────────────────────────────────────
static void unsyncedBlink() {
    ledPower(true);
    clearFrame();
    for (int i = 0; i < HALO_CENTER_COUNT; i++) frame[HALO_MAP[HALO_RING_COUNT + i]] = 0xFF;
    sendFrame();
    delay(100);
    ledsDark();
    uint32_t until = millis() + 1900;
    while ((int32_t)(millis() - until) < 0 && !lbSynced() && powerOk()) {
        lbTempService(1000000);
        __WFI();
    }
}

// ─── Setup / loop ────────────────────────────────────────────────────────────
void setup() {
    pinMode(PA9,  OUTPUT); digitalWrite(PA9,  LOW);
    pinMode(PA12, OUTPUT); digitalWrite(PA12, LOW);
    pinMode(PA15, OUTPUT); ledPower(true);               // LED driver power on for the guard indicator
    pinMode(PF0, INPUT_PULLUP);                          // USB sense (as the stock firmware)
    pinMode(PA2, INPUT);                                 // slide switch, used here only as a wake edge
    attachInterrupt(digitalPinToInterrupt(PF0), onUsbWake, RISING);
    attachSwitchWake();

    // Nothing that can disturb SWD (PA13/PA14 remap, STOP mode, clock
    // changes) may run before this returns.
    lbBootGuard(3000, guardSpinner);

    ledsDark();
}

static uint32_t waitSeq;
static bool sameGridWait() { return lbS.seq == waitSeq && powerOk(); }

void loop() {
    if (powerGate()) return;                             // low battery: window, or sleep until woken
    if (!lbSynced()) { unsyncedBlink(); return; }

    int64_t now    = lbMasterUs();
    int64_t n      = lbBeatIndex(now);                   // most recent show start
    int64_t start  = lbBeatTime(n);
    int64_t showUs = (int64_t)SHOW_FRAMES * SHOW_STEP_MS * 1000;

    if (now - start >= showUs) {                         // between shows: wait for the next one
        if (ledsLeftLit) ledsDark();                     // a resync cut the last show short: do not wait lit for up to a period
        start = lbBeatTime(n + 1);
        waitSeq = lbS.seq;
        // Wake the LED driver shortly before the show. A resync that moves the
        // grid aborts the wait, and the next pass recomputes it.
        if (!lbWaitUntil(start - (int64_t)LED_WAKE_LEAD_MS * 1000, sameGridWait)) return;
        ledPower(true);
        clearFrame();
        sendFrame();
    } else {
        ledPower(true);                                  // joined mid-show
    }
    if (playShow(start)) ledsDark();                     // not after a resync: keep going on the new grid
    else ledsLeftLit = true;                             // ... unless the new grid has no show now (see above)
}
