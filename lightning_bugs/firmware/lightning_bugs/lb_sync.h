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
 * Identity and temperature
 *   The block also carries the chip UID (uid0..3) and die-temperature stats
 *   since the last adopted sync, so each host visit can log which chip it was
 *   and how warm it ran. lbWaitUntil() takes the readings while idle.
 *
 * Wire format and version reporting
 *   The first eight words never change position or meaning:
 *     [0][1] magic   [2] format (major<<16 | minor)   [3] block size in words
 *     [4] firmware version (major<<16 | minor<<8 | patch)   [5] build ID
 *     [6] build flags (bit0: built from a dirty tree)   [7] &uwTick
 *   so a host can always find a block and say what it is, even one it cannot
 *   talk to. Compatibility rule: a different MAJOR is a different layout. A
 *   higher MINOR only appends words at the end (the block size grows); a host
 *   reads each unit with that unit's own layout and decides per command whether
 *   the fields, firmware version and model it has are enough (host/lb_catalog.py).
 *   Changing what a word *means* is a firmware-version matter, recorded there as
 *   a new variant; reordering a word needs a new major.
 *   The layout must match FORMATS in host/lb_catalog.py.
 */
#pragma once
#include <Arduino.h>
#include <stdint.h>
#include "lb_switch.h"
#include "lb_version.h"

// HAL millisecond tick that backs millis(). Its address is published in the
// block so the host can read it directly.
extern "C" { extern volatile uint32_t uwTick; }

#define LB_MAGIC0   0x4C425359u            // 'LBSY'
#define LB_MAGIC1   (LB_MAGIC0 ^ 0xFFFFFFFFu)
#define LB_FORMAT_MAJOR 4u
#define LB_FORMAT_MINOR 0u
#define LB_FORMAT       ((LB_FORMAT_MAJOR << 16) | LB_FORMAT_MINOR)
#define LB_DEFAULT_PERIOD_US 500000u       // 120 BPM until the host says otherwise
#define LB_NO_TEMP  ((int32_t)0x80000000)
#define LB_TEMP_EVERY_MS 10000u            // idle temperature sampling interval

struct LbSyncBlock {
    // ── fixed header: never moves (see "Wire format and version reporting") ──
    uint32_t magic0;                   // [0]  LB_MAGIC0
    uint32_t magic1;                   // [1]  LB_MAGIC1
    uint32_t format;                   // [2]  LB_FORMAT: major<<16 | minor
    uint32_t block_words;              // [3]  size of this struct in 32-bit words
    uint32_t fw_version;               // [4]  LB_FW_VERSION: major<<16 | minor<<8 | patch
    uint32_t fw_build;                 // [5]  git commit (first 8 hex digits), 0 = unknown
    uint32_t fw_flags;                 // [6]  bit0 = built from a dirty tree
    uint32_t tick_addr;                // [7]  &uwTick
    // ── sync ──
    volatile uint32_t seq;             // [8]  seqlock: odd = host mid-write
    volatile uint32_t ack_seq;         // [9]  firmware copies seq once adopted
    volatile uint32_t hold;            // [10] host sets non-zero to stay in boot guard
    volatile uint32_t anchor_tick;     // [11] local millis() at the anchor
    volatile uint32_t anchor_us_lo;    // [12] master µs at the anchor (int64)
    volatile uint32_t anchor_us_hi;    // [13]
    volatile int32_t  corr_ppb;        // [14] master = local * (1 + corr_ppb/1e9)
    volatile uint32_t epoch_us_lo;     // [15] master µs of beat 0 (int64)
    volatile uint32_t epoch_us_hi;     // [16]
    volatile uint32_t period_us;       // [17] beat period
    // ── identity (written once at boot) ──
    uint32_t uid0;                     // [18] chip UID, 16 bytes from 0x1FFF0E00 (little-endian words)
    uint32_t uid1;                     // [19]
    uint32_t uid2;                     // [20]
    uint32_t uid3;                     // [21]
    // ── die temperature, sampled while idle; min/max/sum/n restart when a sync is adopted ──
    volatile int32_t  temp_cdeg;       // [22] latest, 0.01 degC; LB_NO_TEMP if never read
    volatile int32_t  temp_min_cdeg;   // [23] since the last sync was adopted
    volatile int32_t  temp_max_cdeg;   // [24]
    volatile int32_t  temp_sum_cdeg;   // [25] mean = sum / n
    volatile uint32_t temp_n;          // [26] samples in sum
    volatile uint32_t temp_raw;        // [27] latest ADC counts, temperature channel (12-bit)
    volatile uint32_t vref_raw;        // [28] latest ADC counts, VREFINT channel (12-bit)
    volatile uint32_t stats_tick;      // [29] millis() when the temperature stats were last restarted
    // ── battery and power telemetry (no automatic protection: see docs/lightning-bugs/power-policy.md) ──
    volatile uint32_t batt_mv;         // [30] latest supply/battery voltage in mV, 0 = never read
    volatile uint32_t power_state;     // [31] bit0 = reserved (was low-battery latched, always 0), bit1 = USB present
    volatile uint32_t wake_count;      // [32] stop-mode wakes since boot
    // ── board model (the host maps this id to what the board can do; see host/lb_catalog.py) ──
    uint32_t model_id;                 // [33] LB_MODEL_ID
};
#define LB_BLOCK_WORDS (sizeof(LbSyncBlock) / 4)

__attribute__((used, aligned(4))) static LbSyncBlock lbBlock = {
    LB_MAGIC0, LB_MAGIC1, LB_FORMAT, LB_BLOCK_WORDS,
    LB_FW_VERSION, LB_BUILD_ID, (LB_BUILD_DIRTY ? 1u : 0u), (uint32_t)(uintptr_t)&uwTick,
    0, 0, 0, 0, 0, 0, 0, 0, 0, LB_DEFAULT_PERIOD_US,
    0, 0, 0, 0,
    LB_NO_TEMP, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0,
    LB_MODEL_ID
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

// ─── Identity and temperature ────────────────────────────────────────────────
// The chip's own UID (reference manual 4.3: lot, wafer and die X/Y, 16 bytes at
// 0x1FFF0E00, read-only) is the device ID. It needs no per-device build, so two
// units can never end up flashed with the same ID. The host reads it from the block.
//
// The die temperature sensor is read through the ADC (analogRead(ATEMP)) and
// converted with the two factory points TS_CAL1 (30 degC) and TS_CAL2 (85 degC)
// at 0x1FFF0F14 / 0x1FFF0F18, which were taken at Vref+ = 3.3 V. The ADC's
// reference is the supply, so each reading is first scaled by the supply voltage
// that VREFINT (1.2 V) reveals. Both raw readings are published too, so the
// host can redo the arithmetic.
#define LB_UID_ADDR      0x1FFF0E00u
#define LB_TSCAL1_ADDR   0x1FFF0F14u
#define LB_TSCAL2_ADDR   0x1FFF0F18u

static uint16_t lbTsCal1 = 0, lbTsCal2 = 0;
static uint32_t lbTempDueMs = 0;
#define LB_USB_PIN PF0                   // HIGH = USB power present (stock firmware's reading)
static inline bool lbUsbPresent() { return digitalRead(LB_USB_PIN) == HIGH; }

static void lbTempResetStats() {
    lbBlock.temp_min_cdeg = 0x7FFFFFFF;
    lbBlock.temp_max_cdeg = (int32_t)0x80000001;
    lbBlock.temp_sum_cdeg = 0;
    lbBlock.temp_n = 0;
    lbBlock.stats_tick = millis();
}

static void lbIdentityInit() {
    const volatile uint32_t* u = (const volatile uint32_t*)LB_UID_ADDR;
    lbBlock.uid0 = u[0]; lbBlock.uid1 = u[1]; lbBlock.uid2 = u[2]; lbBlock.uid3 = u[3];
    lbTsCal1 = *(const volatile uint16_t*)LB_TSCAL1_ADDR;
    lbTsCal2 = *(const volatile uint16_t*)LB_TSCAL2_ADDR;
    lbTempResetStats();
    lbTempDueMs = millis() + 1000;                    // first reading 1 s after boot
}

static uint32_t lbAdcAvg(uint32_t ch, int n = 4) {
    uint32_t a = 0;
    for (int i = 0; i < n; i++) a += analogRead(ch);
    return (a + n / 2) / n;
}

static void lbTempSample() {
    analogReadResolution(12);
    uint32_t vref = lbAdcAvg(AVREF);
    uint32_t traw = lbAdcAvg(ATEMP);
    lbBlock.vref_raw = vref;
    lbBlock.temp_raw = traw;
    if (vref < 200) return;                           // VREFINT not read: nothing below is trustworthy
    int32_t vcc_mv = (int32_t)((1200u * 4095u + vref / 2) / vref);        // supply = battery, mV
    // Battery and USB telemetry first: they must not depend on the temperature calibration being valid.
    bool usb = lbUsbPresent();
    lbBlock.batt_mv = (uint32_t)vcc_mv;
    lbBlock.power_state = usb ? 2u : 0u;
    if (lbTsCal2 <= lbTsCal1 || lbTsCal2 > 4095) return;
    int32_t norm   = (int32_t)((traw * (uint32_t)vcc_mv + 1650u) / 3300u); // counts at 3.3 V
    int32_t c = 3000 + (5500 * (norm - (int32_t)lbTsCal1)) / ((int32_t)lbTsCal2 - (int32_t)lbTsCal1);
    if (c < -5000 || c > 15000) return;               // outside any plausible vape temperature
    lbBlock.temp_cdeg = c;
    if (c < lbBlock.temp_min_cdeg) lbBlock.temp_min_cdeg = c;
    if (c > lbBlock.temp_max_cdeg) lbBlock.temp_max_cdeg = c;
    lbBlock.temp_sum_cdeg += c;
    lbBlock.temp_n++;
}

// Take a reading if one is due and at least `spare_us` remain before something
// that needs steady timing. The ADC calls are slow compared with one millisecond.
static void lbTempService(int64_t spare_us) {
    if (spare_us < 300000) return;
    if ((int32_t)(millis() - lbTempDueMs) < 0) return;
    lbTempSample();
    lbTempDueMs = millis() + LB_TEMP_EVERY_MS;
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
    lbTempResetStats();                               // temperature stats cover "since this sync"
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
    for (;;) {
        int64_t now = lbMasterUs();
        if (now >= targetUs) break;
        if (keepGoing && !keepGoing()) return false;
        lbTempService(targetUs - now);
        __WFI();
    }
    return true;
}

// Park for at least `ms` after boot, and for as long as the host holds us.
// indicator(elapsed_ms) is called every ~10 ms so the guard is visible.
static void lbBootGuard(uint32_t ms = 3000, void (*indicator)(uint32_t) = nullptr) {
    lbIdentityInit();
    uint32_t start = millis();
    while ((millis() - start) < ms || lbBlock.hold) {
        if (indicator) indicator(millis() - start);
        delay(10);
    }
}
