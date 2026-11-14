/*
 * Lightning Bugs — example beat-synced firmware for the Geek Bar Pulse X Jam
 * (PY32F030EK28 + PLS916H LED driver).
 *
 * Every device synced with host/lb_sync.py flashes on the same shared beat
 * grid. The pattern for each beat is derived only from the beat number n, so
 * devices agree on *what* to show as well as *when*.
 *
 * Unsynced devices blink just the center cluster on their own local grid, so
 * it is obvious which units still need a sync.
 *
 * LED driver code is a trimmed copy of ../../../PY32F030EK28 - Geek Bar Pulse X Jam/.
 * Board: Generic PY32F030 (py32duino). Flash with pyocd as in the main README.
 */
#include <Arduino.h>
#include <string.h>
#include "matrix_map.h"
#include "lb_sync.h"

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

static inline void on(uint8_t idx) { if (idx < 144) frame[idx] = 0xFF; }
static inline void clearFrame()    { memset(frame, 0, sizeof frame); }

// ─── Boot guard indicator: single halo LED spinning ──────────────────────────
static void guardSpinner(uint32_t elapsedMs) {
    clearFrame();
    on(HALO_MAP[(elapsedMs / 80) % HALO_RING_COUNT]);
    if (lbBlock.hold) for (int i = 0; i < HALO_CENTER_COUNT; i++) on(HALO_MAP[HALO_RING_COUNT + i]);
    sendFrame();
}

// ─── Beat patterns: a pure function of the beat number ───────────────────────
static void renderBeat(int64_t n) {
    clearFrame();
    if (!lbSynced()) {                                   // "I need a sync"
        for (int i = 0; i < HALO_CENTER_COUNT; i++) on(HALO_MAP[HALO_RING_COUNT + i]);
        return;
    }
    uint64_t u          = (uint64_t)n;
    uint32_t beatInBar  = u % 4;                         // 4 beats per bar
    uint32_t phrase     = (u / 32) % 4;                  // switch pattern every 8 bars
    switch (phrase) {
        case 0:                                          // halo position steps each beat
            on(HALO_MAP[u % HALO_RING_COUNT]);
            if (beatInBar == 0) for (int i = 0; i < HALO_CENTER_COUNT; i++) on(HALO_MAP[HALO_RING_COUNT + i]);
            break;
        case 1: {                                        // outer ring, 5-LED chunk chase
            uint32_t chunk = u % 10;
            for (int i = 0; i < 5; i++) on(OUTER_SWEEP[chunk * 5 + i]);
            break;
        }
        case 2: {                                        // level bars count up through a bar
            uint32_t level = (u % 8) + 2;
            for (uint32_t l = 0; l < level && l < 10; l++)
                for (int i = 0; i < 16 && BAR_LEVELS[l][i] != 0xFF; i++) on(BAR_LEVELS[l][i]);
            break;
        }
        default:                                         // downbeat = everything
            if (beatInBar == 0) memset(frame, 0xFF, sizeof frame);
            else                on(HALO_MAP[u % HALO_RING_COUNT]);
            break;
    }
}

// ─── Setup / loop ────────────────────────────────────────────────────────────
void setup() {
    pinMode(PA9,  OUTPUT); digitalWrite(PA9,  LOW);
    pinMode(PA12, OUTPUT); digitalWrite(PA12, LOW);
    pinMode(PA15, OUTPUT); digitalWrite(PA15, LOW);      // LED driver power on

    // Nothing that can disturb SWD (PA13/PA14 remap, STOP mode, clock
    // changes) may run before this returns.
    lbBootGuard(3000, guardSpinner);

    clearFrame();
    sendFrame();
}

void loop() {
    int64_t n     = lbBeatIndex(lbMasterUs()) + 1;       // next beat on the grid
    int64_t start = lbBeatTime(n);
    int64_t flash = lbPeriodUs() / 4;
    if (flash > 120000) flash = 120000;

    lbWaitUntil(start);
    renderBeat(n);
    sendFrame();

    lbWaitUntil(start + flash);
    clearFrame();
    sendFrame();
    // A resync that moves time backwards just means the next wait is longer;
    // one that moves it forwards skips ahead. Either way we stay on the grid.
}
