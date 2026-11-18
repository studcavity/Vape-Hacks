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

static void ledsDark() {                  // blank the driver, then cut its power
    clearFrame();
    sendFrame();
    ledPower(false);
}

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
static bool sameSync() { return lbS.seq == seqAtStart; }

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
    while ((int32_t)(millis() - until) < 0 && !lbSynced()) {
        lbTempService(1000000);
        __WFI();
    }
}

// ─── Setup / loop ────────────────────────────────────────────────────────────
void setup() {
    pinMode(PA9,  OUTPUT); digitalWrite(PA9,  LOW);
    pinMode(PA12, OUTPUT); digitalWrite(PA12, LOW);
    pinMode(PA15, OUTPUT); ledPower(true);               // LED driver power on for the guard indicator

    // Nothing that can disturb SWD (PA13/PA14 remap, STOP mode, clock
    // changes) may run before this returns.
    lbBootGuard(3000, guardSpinner);

    ledsDark();
}

static uint32_t waitSeq;
static bool sameGridWait() { return lbS.seq == waitSeq; }

void loop() {
    if (!lbSynced()) { unsyncedBlink(); return; }

    int64_t now    = lbMasterUs();
    int64_t n      = lbBeatIndex(now);                   // most recent show start
    int64_t start  = lbBeatTime(n);
    int64_t showUs = (int64_t)SHOW_FRAMES * SHOW_STEP_MS * 1000;

    if (now - start >= showUs) {                         // between shows: wait for the next one
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
}
