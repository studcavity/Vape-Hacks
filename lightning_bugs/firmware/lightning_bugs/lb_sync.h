/*
 * lb_sync.h — Lightning Bugs shared-clock support for PY32F030 (py32duino core)
 *
 * Gives the firmware an estimate of the host computer's wall clock ("master
 * time", Unix microseconds) plus a shared beat grid, so that several devices
 * synced to the same computer fire effects at the same moments.
 *
 * How it works
 *   - A small struct (lbBlock) lives in RAM, tagged with a magic number.
 *   - host/lb_sync.py attaches over SWD *without halting the core*, finds the
 *     block by scanning RAM for the magic, measures this chip's millisecond
 *     counter (uwTick) against the host clock, and writes back:
 *       anchor  — a (local tick, master µs) pair
 *       corr    — this chip's clock-rate error in parts-per-billion
 *       epoch / period — the shared beat grid
 *   - Firmware turns millis() into master time with:
 *       master_us = anchor_us + L*1000 + L*corr_ppb/1e6,  L = millis() - anchor_tick
 *     host/lb_sync.py uses the exact same formula to check drift later.
 *
 * Schedule against absolute times, never chains of delay():
 *     int64_t n = lbBeatIndex(lbMasterUs()) + 1;  // next beat
 *     lbWaitUntil(lbBeatTime(n));                  // sleeps (WFI) until it
 *     ...render beat n...                          // pattern derived from n
 *
 * Boot guard
 *   Call lbBootGuard() at the top of setup(). Anything that could make SWD
 *   unreachable (remapping PA13/PA14, STOP mode, clock changes) must come
 *   AFTER it. During the guard window the host can run `lb_sync.py hold` to
 *   keep the chip parked in the guard (SWD alive) so it can be reflashed.
 *
 * The block layout must match BLOCK_FIELDS in host/lb_sync.py. Bump
 * LB_VERSION on any layout change.
 */
#pragma once
#include <Arduino.h>
#include <stdint.h>

// HAL millisecond tick that backs millis(). Its address is published in the
// block so the host can read it directly.
extern "C" { extern volatile uint32_t uwTick; }

#define LB_MAGIC0   0x4C425359u            // 'LBSY'
#define LB_MAGIC1   (LB_MAGIC0 ^ 0xFFFFFFFFu)
#define LB_VERSION  1u
#define LB_DEFAULT_PERIOD_US 500000u       // 120 BPM until the host says otherwise

struct LbSyncBlock {
    uint32_t magic0;                   // [0]  LB_MAGIC0
    uint32_t magic1;                   // [1]  LB_MAGIC1
    uint32_t version;                  // [2]  LB_VERSION
    uint32_t tick_addr;                // [3]  &uwTick
    volatile uint32_t seq;             // [4]  seqlock: odd = host mid-write
    volatile uint32_t ack_seq;         // [5]  firmware copies seq once adopted
    volatile uint32_t hold;            // [6]  host sets non-zero to stay in boot guard
    volatile uint32_t anchor_tick;     // [7]  local millis() at the anchor
    volatile uint32_t anchor_us_lo;    // [8]  master µs at the anchor (int64)
    volatile uint32_t anchor_us_hi;    // [9]
    volatile int32_t  corr_ppb;        // [10] master = local * (1 + corr_ppb/1e9)
    volatile uint32_t epoch_us_lo;     // [11] master µs of beat 0 (int64)
    volatile uint32_t epoch_us_hi;     // [12]
    volatile uint32_t period_us;       // [13] beat period
};

__attribute__((used, aligned(4))) static LbSyncBlock lbBlock = {
    LB_MAGIC0, LB_MAGIC1, LB_VERSION, (uint32_t)(uintptr_t)&uwTick,
    0, 0, 0, 0, 0, 0, 0, 0, 0, LB_DEFAULT_PERIOD_US
};

// Firmware-side snapshot, refreshed from lbBlock whenever seq changes.
struct LbState {
    bool     synced;
    uint32_t seq;
    uint32_t anchor_tick;
    int64_t  anchor_us;
    int32_t  corr_ppb;
    int64_t  epoch_us;
    uint32_t period_us;
};
static LbState lbS = { false, 0, 0, 0, 0, 0, LB_DEFAULT_PERIOD_US };

static inline int64_t lbJoin64(uint32_t lo, uint32_t hi) {
    return (int64_t)(((uint64_t)hi << 32) | lo);
}

// Adopt a new sync from the host if one has been fully written.
static void lbPoll() {
    uint32_t s1 = lbBlock.seq;
    if (s1 == lbS.seq || (s1 & 1u)) return;          // unchanged, or host mid-write
    LbState n;
    n.anchor_tick = lbBlock.anchor_tick;
    n.anchor_us   = lbJoin64(lbBlock.anchor_us_lo, lbBlock.anchor_us_hi);
    n.corr_ppb    = lbBlock.corr_ppb;
    n.epoch_us    = lbJoin64(lbBlock.epoch_us_lo, lbBlock.epoch_us_hi);
    n.period_us   = lbBlock.period_us;
    if (lbBlock.seq != s1) return;                    // torn read; retry next poll
    if (n.period_us == 0) return;                     // refuse a nonsense grid
    n.synced = true;
    n.seq    = s1;
    lbS = n;
    lbBlock.ack_seq = s1;
}

static inline bool lbSynced() { lbPoll(); return lbS.synced; }

// Master time (Unix µs if synced, else local µs since boot). 1 ms granularity.
static int64_t lbMasterUs() {
    lbPoll();
    uint32_t t = millis();
    if (!lbS.synced) return (int64_t)t * 1000;
    int64_t L = (int32_t)(t - lbS.anchor_tick);      // signed: valid ±24 days
    return lbS.anchor_us + L * 1000 + (L * lbS.corr_ppb) / 1000000;
}

static inline int64_t lbFloorDiv(int64_t a, int64_t b) {
    int64_t q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}

static inline uint32_t lbPeriodUs()          { lbPoll(); return lbS.period_us; }
static inline int64_t  lbBeatIndex(int64_t us) { return lbFloorDiv(us - lbS.epoch_us, lbS.period_us); }
static inline int64_t  lbBeatTime(int64_t n)   { return lbS.epoch_us + n * (int64_t)lbS.period_us; }

// Sleep (WFI, woken by the 1 ms SysTick) until master time >= targetUs.
// keepGoing() is polled each wakeup; return false from it to abort.
static bool lbWaitUntil(int64_t targetUs, bool (*keepGoing)() = nullptr) {
    while (lbMasterUs() < targetUs) {
        if (keepGoing && !keepGoing()) return false;
        __WFI();
    }
    return true;
}

// Park for at least `ms` after boot, and for as long as the host holds us.
// indicator(elapsed_ms) is called every ~10 ms so the guard is visible.
static void lbBootGuard(uint32_t ms = 3000, void (*indicator)(uint32_t) = nullptr) {
    uint32_t start = millis();
    while ((millis() - start) < ms || lbBlock.hold) {
        if (indicator) indicator(millis() - start);
        delay(10);
    }
}
