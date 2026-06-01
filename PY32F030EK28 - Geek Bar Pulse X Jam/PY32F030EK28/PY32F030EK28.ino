/*
 * GeekBar Pulse X Jam
 * PY32F030EK28 microcontroller with a PLS916H LED matrix driver 
 *
 * Adapted from sm2013-vapehack/geekbar_pulse_x_screen_reuse.
 * Uses bit-bang SPI on PA9 (SCK) and PA12 (MOSI) to match the original
 * PCB trace. Hardware SPI is NOT used because PA9/PA12 are not the
 * default SPI1 pins; bit-bang at ~1 MHz is sufficient.
 * PA15 enables the LED driver power transistor (PNP high-side, active LOW).
 *
 * Board:   Generic PY32F030 (py32duino / arduino-py32 core)
 *          This specific board has SCK and SWD exposed through the USB-C port, so you can either solder to the pulldowns 2.5k?)
 *          or get a USB-C breakout/cable and attach to the USB's A5 and B5 pins.
 * 
 * Upload:  OpenOCD + Pi Pico picoprobe via SWD (or any SWD device)
 *          example flash command: pyocd flash -u <your swd probe sn> -t py32f030x8 -f 500000 main.ino.bin
 *          
 * Binary backup: backup_flash.bin is the dumped flash memory as a binary file. backup_flash_full.s was decompiled by claude.
 *                To do this yourself, run something like:
 *                pyocd read -u <your debugger sn> -t py32f030x8 --base 0x08000000 --count 65536 -o backup_flash.bin
 *                These microcontrollers usually don't have read protection enabled, and the boot selector pin didn't
 *                need to be forcibly pulled high. This makes sense imo from a production standpoint, like who cares
 */

#include <Arduino.h>
#include <string.h>
#include <stdio.h>
#include "matrix_map.h"

extern volatile bool btnEdge;  // defined below, used by animation functions
static int  animSwitchPos = 2; // switch position captured when animation starts
static bool animOK();          // true while animation should keep running (forward decl)

// ─── SPI bit-bang macros ──────────────────────────────────────────────────────
// BSRR atomic set/reset is used in the hot send path for timing.
// Pins are configured by the Arduino library in setup() below.

// PA9=SCK, PA12=MOSI: BSRR bit N sets HIGH, bit N+16 sets LOW
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

// Termination byte at ~200 kHz
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

// ─── Frame buffers ───────────────────────────────────────────────────────────
static uint8_t frameDigits[144];
static uint8_t frameHalo[144];
static uint8_t frameOut[144];

// ─── PLS916H protocol ────────────────────────────────────────────────────────
static void writePLS916H(const uint8_t data[144]) {
    static const uint8_t header[13] = {
        0x5A,0xFF,0x01,0x5A,0x24,0x21,0x3D,0x01,0x83,0x5A,0xFF,0x02,0x5B
    };
    static const uint8_t tail[4] = {0x5A,0xFF,0x04,0x5D};

    uint8_t chk = 0;
    for (int i = 0; i < 144; i++) chk += data[i];

    for (int i = 0; i < 13;  i++) spiByteFast(header[i]);
    for (int i = 0; i < 144; i++) spiByteFast(data[i]);
    spiByteFast(chk);
    for (int i = 0; i < 4;   i++) spiByteFast(tail[i]);
    spiByteTerminate(0x00);
}

// ─── Frame helpers ───────────────────────────────────────────────────────────
static void setBitBuf(uint8_t *buf, uint8_t byteIdx, uint8_t bitIdx, bool on) {
    if (byteIdx >= 144) return;
    if (bitIdx  >    7) return;
    if (on) buf[byteIdx] |=  (uint8_t)(1 << bitIdx);
    else    buf[byteIdx] &= ~(uint8_t)(1 << bitIdx);
}

static inline void setDigitBit(int8_t byteIdx, int8_t bitIdx, bool on) {
    setBitBuf(frameDigits, byteIdx, bitIdx, on);
}
static inline void setHaloBit(int8_t byteIdx, int8_t bitIdx, bool on) {
    setBitBuf(frameHalo, byteIdx, bitIdx, on);
}

static void composeAndSend() {
    for (int i = 0; i < 144; i++) frameOut[i] = frameDigits[i] | frameHalo[i];
    writePLS916H(frameOut);
}

static void digitsClear() { memset(frameDigits, 0, 144); }
static void haloClear()   { memset(frameHalo,   0, 144); }
static void allClear()    { digitsClear(); haloClear(); }

// ─── Digit display ───────────────────────────────────────────────────────────
static void clearDigit(int d) {
    if (d < 0 || d > 5) return;
    for (int s = 0; s < 7; s++) {
        Segment seg = DIGIT_SEG[d][s];
        if (seg.byteIdx < 144) setDigitBit(seg.byteIdx, seg.bitIdx, false);
    }
}

static void displayDigit(int d, int val) {
    if (d < 0 || d > 5 || val < 0 || val > 9) return;
    if (d <= 1) {
        // Partial digit — only draws "1" (uses segments B and C only)
        if (val != 1) return;
        clearDigit(d);
        for (int s = 0; s < 7; s++) {
            Segment seg = DIGIT_SEG[d][s];
            if (seg.byteIdx < 144) setDigitBit(seg.byteIdx, seg.bitIdx, true);
        }
        return;
    }
    clearDigit(d);
    for (int s = 0; s < 7; s++) {
        if (NUMBER_TABLE[val][s]) {
            Segment seg = DIGIT_SEG[d][s];
            if (seg.byteIdx >= 0) setDigitBit(seg.byteIdx, seg.bitIdx, true);
        }
    }
}

// top: true = top num display, false = bottom num display
// value s are 0..199 (hundreds place is just a line)
static void displayNumber(bool top, int value) {
    int pIdx = top ? 0 : 1;
    int tIdx = top ? 2 : 4;
    int oIdx = top ? 3 : 5;
    clearDigit(pIdx); clearDigit(tIdx); clearDigit(oIdx);
    if (value < 0) return;
    if (value / 100 == 1)   displayDigit(pIdx, 1);
    if (value >= 10)        displayDigit(tIdx, (value / 10) % 10);
    displayDigit(oIdx, value % 10);
}

// Write a digit into frameDigits using full bytes (0xFF = on, 0x00 = off).
// Required when frameDigits has a 0xFF background: setBitBuf clears only one
// bit, leaving 0xF7 which is still non-zero (LED stays on).
static void setDigitBytes(int d, int val) {
    if (d < 0 || d > 5 || val < 0 || val > 9) return;
    for (int s = 0; s < 7; s++) {
        Segment seg = DIGIT_SEG[d][s];
        if (seg.byteIdx >= 144) continue;
        bool on = (d <= 1) ? (val == 1 && (s == 1 || s == 2))
                           : NUMBER_TABLE[val][s];
        frameDigits[seg.byteIdx] = on ? 0xFF : 0x00;
    }
}

// ─── Animations (all use byte-addressed frame: write 0x08 = on, 0x00 = off) ─
// Bit-3 helper for frameDigits — used by bar-level fill.
static inline void setOuter(uint8_t b, bool on) {
    setBitBuf(frameDigits, b, 3, on);
}
static inline void setExtra(uint8_t val) {
    for (int i = 0; i < EXTRA_COUNT; i++) frameDigits[EXTRA_LEDS[i]] = val;
}

// Pulse halo (and optionally outer ring) for the given number of cycles.
// stepMs controls speed: 256 steps × stepMs ms = cycle length (stepMs=8 → ~2 s).
static void breathe(int cycles = 1, int stepMs = 8, bool includeOuter = false) {
    for (int c = 0; c < cycles && animOK(); c++) {
        for (int step = 0; step < 256 && animOK(); step++) {
            uint8_t b = BREATHE_TABLE[step];
            for (int i = 0; i < HALO_COUNT; i++)
                frameHalo[HALO_MAP[i]] = b;
            if (includeOuter) {
                for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b;
                setExtra(b);
            }
            composeAndSend();
            delay(stepMs);
        }
    }
    haloClear();
    if (includeOuter) {
        for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
        setExtra(0);
    }
    composeAndSend();
}

// Bar fill — lights every LED in levels 0..level (cumulative)
static void barSetLevel(int level, bool on) {
    for (int l = 0; l <= level && l < 10; l++) {
        for (int i = 0; BAR_LEVELS[l][i] != 0xFF; i++)
            setOuter(BAR_LEVELS[l][i], on);
    }
}
static void barFillUp(int holdMs = 400) {
    for (int l = 0; l < 10 && animOK(); l++) {
        barSetLevel(l, true);
        composeAndSend();
        delay(holdMs / 10);
    }
    uint32_t holdEnd = millis() + (uint32_t)holdMs;
    while (animOK() && (int32_t)(millis() - holdEnd) < 0) delay(20);
    barSetLevel(9, false);
    composeAndSend();
}

// ─── Halo helpers ────────────────────────────────────────────────────────────
static void setHalo(int idx, bool on) {
    if (idx < 0 || idx >= HALO_COUNT) return;
    setBitBuf(frameHalo, HALO_MAP[idx], 3, on);
}

static void haloAll(bool on) {
    for (int i = 0; i < HALO_COUNT; i++) setHalo(i, on);
}

static void haloChase(int delayMs = 50) {
    for (int i = 0; i < HALO_RING_COUNT && animOK(); i++) {
        uint8_t cb = BREATHE_TABLE[(uint8_t)((uint32_t)i * 256 / HALO_RING_COUNT)];
        for (int c = 0; c < HALO_CENTER_COUNT; c++)
            frameHalo[HALO_MAP[HALO_RING_COUNT + c]] = cb;
        setHalo(i, true);  composeAndSend(); delay(delayMs);
        setHalo(i, false); composeAndSend();
    }
    haloClear(); composeAndSend();
}

static bool handleBitAddress(String cmd) {
    cmd.trim();
    bool toHalo = false;
    bool turnOn = true;
    if (cmd.startsWith("h:") || cmd.startsWith("H:")) { toHalo = true;  cmd = cmd.substring(2); cmd.trim(); }
    else if (cmd.startsWith("d:") || cmd.startsWith("D:")) { toHalo = false; cmd = cmd.substring(2); cmd.trim(); }
    if (cmd.startsWith("!")) { turnOn = false; cmd = cmd.substring(1); cmd.trim(); }
    int comma = cmd.indexOf(',');
    if (comma < 0) return false;
    int b   = cmd.substring(0, comma).toInt();
    int bit = cmd.substring(comma + 1).toInt();
    if (b < 0 || b >= 144 || bit < 0 || bit > 7) return false;
    if (toHalo) setHaloBit(b, bit, turnOn);
    else        setDigitBit(b, bit, turnOn);
    composeAndSend();
    return true;
}

// Average n AVREF readings. n=5 reduces single-sample noise
// Two sources of noise in the analog readings:
//   1. The py32duino library disables Vrefint after every analogRead(AVREF) via
//      LL_ADC_PATH_INTERNAL_NONE, so it restarts cold each call. The HAL provides
//      ~14 μs settle time (calibration), but the datasheet requires up to 17 μs,
//      so roughly 1 in 6 reads catches Vrefint still ramping — giving a slightly
//      high rawVref → slightly low mV estimate.
//   2. VDD itself has small transients from bit-bang SPI switching and LED load.
static int analogSample(int pin, int n = 5) {
    long sum = 0;
    for (int i = 0; i < n; i++) sum += analogRead(pin);
    return (int)(sum / n);
}

// ─── Battery percentage ───────────────────────────────────────────────────────
// MCU VDD is powered directly from the LiPo cell, so VDD = Vbattery.
// You cannot read battery voltage on an ADC pin — it would equal VDDA.
// Instead, read Vrefint (1.2V internal reference) and invert:
//   Vbattery_mV = 1200 * 4095 / rawVref
//
// EMA on computed mV inside readBatteryPercent: prevents table threshold
//     crossings from causing percentage jumps on individual noisy reads.

// Lookup table extracted from original firmware at flash 0x08007850.
// 20 entries in 5% steps covering ~3507 mV (0%) to 4075 mV (100%).
static const uint16_t BATT_MV_TABLE[20] = {
    3507, 3587, 3619, 3643, 3661, 3675, 3687, 3697, 3709, 3721,
    3746, 3766, 3793, 3822, 3852, 3882, 3912, 3972, 4012, 4075,
};

// Returns battery percentage 0–100 in 5% steps.
static int readBatteryPercent() {
    int rawVref = analogSample(AVREF);
    int mv = (long)1200 * 4095 / rawVref;
    // EMA (alpha=1/4): smooths noise without hiding real battery level changes.
    static int smoothedMv = 0;
    smoothedMv = (smoothedMv == 0) ? mv : (3 * smoothedMv + mv + 2) / 4;
    for (int i = 0; i < 20; i++) {
        if (BATT_MV_TABLE[i] >= smoothedMv) return i * 5;
    }
    return 100;
}

// ─── Charging detection ───────────────────────────────────────────────────────
// Original firmware reads PF0 with HAL_GPIO_ReadPin(GPIOF, 0x0001):
//   PF0 HIGH = USB power present  (VBUS sense or LP4068 PG pin)
//   PF0 LOW  = no USB
// LP4068 CHRG pin on PB5:
//   PB5 LOW  = battery charging in progress  (open-drain, active-low)
//   PB5 HIGH = charging complete or no USB
static bool usbPresent()  { return digitalRead(PF0) == HIGH; }
static bool isCharging()  { return usbPresent() && (digitalRead(PB5) == LOW); }
static bool chargeDone()  { return usbPresent() && (digitalRead(PB5) == HIGH); }

// ─── Switch / power state ─────────────────────────────────────────────────────
// Three-position switch wired to PA2:
//   Position 1: PA2 driven to just above GND
//   Position 2: PA2 driven to Vbat
//   Position 3: PA2 driven to GND
static int readSwitch() {
    int val = analogSample(PA2);
    // remember, 4095 max value = 3.3V
    if (val < 20) { // pos 1 = sleep (left)
        return 1;
    } else if (val > 2000) { // pos 2 (middle)
        return 2;
    } else return 3; // pos 3 (right)
}
static bool animOK() { return !btnEdge && readSwitch() == animSwitchPos; }

static void sleepDisplay() {
    allClear();
    composeAndSend();          // send blank frame so the driver chip is cleared
    digitalWrite(PA15, HIGH);  // PNP switch off — cuts power to LED driver
}

static void wakeDisplay() {
    digitalWrite(PA15, LOW);   // PNP switch on — restores LED driver power
}

// Comet-tail chase: leading dot + 2-position dimming trail wrapping around halo.
static void haloCometChase(int delayMs = 50) {
    for (int i = 0; i < HALO_RING_COUNT && animOK(); i++) {
        haloClear();
        // center pulse — breathe one full cycle per ring revolution
        uint8_t cb = BREATHE_TABLE[(uint8_t)((uint32_t)i * 256 / HALO_RING_COUNT)];
        for (int c = 0; c < HALO_CENTER_COUNT; c++)
            frameHalo[HALO_MAP[HALO_RING_COUNT + c]] = cb;
        // comet — trail wraps within ring only
        frameHalo[HALO_MAP[i]]                                              = 0xFF;
        frameHalo[HALO_MAP[(i - 1 + HALO_RING_COUNT) % HALO_RING_COUNT]]   = 0x50;
        frameHalo[HALO_MAP[(i - 2 + HALO_RING_COUNT) % HALO_RING_COUNT]]   = 0x18;
        composeAndSend();
        delay(delayMs);
    }
    haloClear();
    composeAndSend();
}

// Progressive halo fill: light LEDs one-by-one then clear in reverse.
static void haloFill(int holdMs = 200, int stepMs = 80) {
    haloClear();
    for (int i = 0; i < HALO_COUNT && animOK(); i++) {
        frameHalo[HALO_MAP[i]] = 0xFF;
        composeAndSend();
        delay(stepMs);
    }
    uint32_t holdEnd = millis() + (uint32_t)holdMs;
    while (animOK() && (int32_t)(millis() - holdEnd) < 0) delay(20);
    for (int i = HALO_COUNT - 1; i >= 0 && animOK(); i--) {
        frameHalo[HALO_MAP[i]] = 0;
        composeAndSend();
        delay(stepMs);
    }
    haloClear();
    composeAndSend();
}

// ─── Fade / sparkle / physics animations ─────────────────────────────────────

// Random LEDs on halo + outer ring ignite at full brightness and fade out each frame.
static void sparkle(int durationMs = 4000, int density = 6, int fadeStep = 25) {
    uint8_t bright[144];
    memset(bright, 0, sizeof(bright));
    uint32_t end = millis() + (uint32_t)durationMs;
    while (animOK() && (int32_t)(millis() - end) < 0) {
        for (int i = 0; i < density; i++) {
            bright[OUTER_SWEEP[random(OUTER_SWEEP_COUNT)]] = 0xFF;
            bright[HALO_MAP[random(HALO_COUNT)]]           = 0xFF;
            bright[EXTRA_LEDS[random(EXTRA_COUNT)]]        = 0xFF;
        }
        for (int i = 0; i < OUTER_SWEEP_COUNT; i++) {
            uint8_t idx = OUTER_SWEEP[i];
            frameDigits[idx] = bright[idx];
            bright[idx] = bright[idx] > fadeStep ? bright[idx] - fadeStep : 0;
        }
        for (int i = 0; i < HALO_COUNT; i++) {
            uint8_t idx = HALO_MAP[i];
            frameHalo[idx] = bright[idx];
            bright[idx] = bright[idx] > fadeStep ? bright[idx] - fadeStep : 0;
        }
        for (int i = 0; i < EXTRA_COUNT; i++) {
            uint8_t idx = EXTRA_LEDS[i];
            frameDigits[idx] = bright[idx];
            bright[idx] = bright[idx] > fadeStep ? bright[idx] - fadeStep : 0;
        }
        composeAndSend();
        delay(30);
    }
    for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
    for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = 0;
    setExtra(0);
    composeAndSend();
}

// Energy pulse: halo fades in, cross-fades to outer ring, outer fades out.
static void ripple(int cycles = 4, int stepMs = 20) {
    for (int c = 0; c < cycles && animOK(); c++) {
        for (int b = 0; b <= 255 && animOK(); b += 17) {
            for (int i = 0; i < HALO_COUNT; i++) frameHalo[HALO_MAP[i]] = b;
            composeAndSend(); delay(stepMs);
        }
        for (int b = 0; b <= 255 && animOK(); b += 17) {
            uint8_t inner = 255 - b, outer = b;
            for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = inner;
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = outer;
            setExtra(outer);
            composeAndSend(); delay(stepMs);
        }
        for (int b = 255; b >= 0 && animOK(); b -= 17) {
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b;
            setExtra(b);
            composeAndSend(); delay(stepMs);
        }
    }
    for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = 0;
    for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
    setExtra(0);
    composeAndSend();
}

// Expanding burst explosions on the outer ring; halo flashes on each ignition.
static void fireworks(int durationMs = 6000) {
    struct Burst { int8_t center; uint8_t age; };
    const int N = 3;
    Burst bursts[N];
    for (int i = 0; i < N; i++) bursts[i].age = 255;

    uint8_t ringBright[OUTER_SWEEP_COUNT];
    uint32_t end      = millis() + (uint32_t)durationMs;
    uint32_t nextFire = millis() + 300;

    while (animOK() && (int32_t)(millis() - end) < 0) {
        if ((int32_t)(millis() - nextFire) >= 0) {
            for (int i = 0; i < N; i++) {
                if (bursts[i].age >= 11) {
                    bursts[i].center = random(OUTER_SWEEP_COUNT);
                    bursts[i].age    = 0;
                    for (int h = 0; h < HALO_COUNT; h++) frameHalo[HALO_MAP[h]] = 0xC0;
                    setExtra(0xC0);
                    break;
                }
            }
            nextFire = millis() + 500 + random(800);
        }
        for (int h = 0; h < HALO_COUNT; h++) {
            uint8_t &v = frameHalo[HALO_MAP[h]];
            v = v > 30 ? v - 30 : 0;
        }
        for (int i = 0; i < EXTRA_COUNT; i++) {
            uint8_t &v = frameDigits[EXTRA_LEDS[i]];
            v = v > 30 ? v - 30 : 0;
        }
        memset(ringBright, 0, sizeof(ringBright));
        for (int b = 0; b < N; b++) {
            if (bursts[b].age >= 11) continue;
            uint8_t age  = bursts[b].age;
            int spread   = age * 2;
            int base     = 255 - age * 23;
            if (base < 0) base = 0;
            for (int d = -spread; d <= spread; d++) {
                int ri  = ((int)bursts[b].center + d + OUTER_SWEEP_COUNT) % OUTER_SWEEP_COUNT;
                int val = base - (d < 0 ? -d : d) * 14;
                if (val < 0) val = 0;
                if ((uint8_t)val > ringBright[ri]) ringBright[ri] = val;
            }
            bursts[b].age++;
        }
        for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = ringBright[i];
        composeAndSend();
        delay(50);
    }
    for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
    for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = 0;
    setExtra(0);
    composeAndSend();
}

// Double-pulse heartbeat rhythm on halo + outer ring: thump-thump ... thump-thump ...
static void heartbeat(int bpm = 70, int cycles = 6) {
    int period = 60000 / bpm;
    for (int c = 0; c < cycles && animOK(); c++) {
        for (int b = 0; b <= 255 && animOK(); b += 51) {
            for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = b;
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b >> 1;
            setExtra(b >> 1);
            composeAndSend(); delay(10);
        }
        for (int b = 255; b >= 0 && animOK(); b -= 17) {
            for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = b;
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b >> 1;
            setExtra(b >> 1);
            composeAndSend(); delay(10);
        }
        uint32_t gap = millis() + 100;
        while (animOK() && (int32_t)(millis() - gap) < 0) delay(5);
        for (int b = 0; b <= 178 && animOK(); b += 44) {
            for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = b;
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b >> 1;
            setExtra(b >> 1);
            composeAndSend(); delay(10);
        }
        for (int b = 178; b >= 0 && animOK(); b -= 22) {
            for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = b;
            for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = b >> 1;
            setExtra(b >> 1);
            composeAndSend(); delay(10);
        }
        int restMs = period - 470;
        if (restMs < 10) restMs = 10;
        uint32_t restEnd = millis() + restMs;
        while (animOK() && (int32_t)(millis() - restEnd) < 0) delay(10);
    }
    for (int i = 0; i < HALO_COUNT;        i++) frameHalo[HALO_MAP[i]]      = 0;
    for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
    setExtra(0);
    composeAndSend();
}

// Multiple comets with trailing fade on the outer ring.
static void meteorShower(int durationMs = 6000) {
    const int N = 4;
    int32_t pos[N];
    const int speeds[N] = {3, 5, 2, 4};
    const int TRAIL = 10;
    const uint8_t trailBright[TRAIL + 1] = {0xFF,0xD0,0xA0,0x78,0x58,0x40,0x2C,0x1C,0x10,0x08,0x04};
    for (int i = 0; i < N; i++) pos[i] = (int32_t)random(OUTER_SWEEP_COUNT) * 16;
    setExtra(0x20);  // dim static starfield on bar/icon LEDs

    uint32_t end = millis() + (uint32_t)durationMs;
    while (animOK() && (int32_t)(millis() - end) < 0) {
        for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
        for (int m = 0; m < N; m++) {
            pos[m] += speeds[m];
            if (pos[m] >= (int32_t)OUTER_SWEEP_COUNT * 16) pos[m] -= (int32_t)OUTER_SWEEP_COUNT * 16;
            int head = pos[m] / 16;
            for (int t = 0; t <= TRAIL; t++) {
                int ri = (head - t + OUTER_SWEEP_COUNT) % OUTER_SWEEP_COUNT;
                uint8_t &cell = frameDigits[OUTER_SWEEP[ri]];
                if (trailBright[t] > cell) cell = trailBright[t];
            }
        }
        composeAndSend();
        delay(16);
    }
    for (int i = 0; i < OUTER_SWEEP_COUNT; i++) frameDigits[OUTER_SWEEP[i]] = 0;
    setExtra(0);
    composeAndSend();
}

// ALL LEDs (digits, halo, outer ring, bar zone).  Each LED is assigned an
// approximate x-column (0–15); 0xFF = not a known LED position.
// This was supposed to be a horizontal sweep, but it looks cool this way too
static void raveAnimation(int stepMs = 35, int passes = 2) {
    allClear();
    const int COLS = 16;

    for (int pass = 0; pass < passes && animOK(); pass++) {
        for (int col = 0; col < COLS && animOK(); col++) {
            digitsClear();
            for (int i = 0; i < 144; i++) {
                if (RAVE_SWEEP[i] >= COLS) continue;
                int dx = col - (int)RAVE_SWEEP[i];
                uint8_t b = (dx == 0) ? 0xFF : (dx == 1) ? 0x60 : (dx == 2) ? 0x18 : 0;
                frameDigits[i] = b;
            }
            composeAndSend();
            delay(stepMs);
        }
        for (int col = COLS - 1; col >= 0 && animOK(); col--) {
            digitsClear();
            for (int i = 0; i < 144; i++) {
                if (RAVE_SWEEP[i] >= COLS) continue;
                int dx = (int)RAVE_SWEEP[i] - col;
                uint8_t b = (dx == 0) ? 0xFF : (dx == 1) ? 0x60 : (dx == 2) ? 0x18 : 0;
                frameDigits[i] = b;
            }
            composeAndSend();
            delay(stepMs);
        }
    }
    allClear();
    composeAndSend();
}

// ─── Button (PB1, active-low) ────────────────────────────────────────────────
// FALLING-edge ISR: first edge sets btnEdge immediately.
// 10 ms lockout covers same-edge contact bounce only; release debounce is
// handled in loop() by requiring the pin to be HIGH for RELEASE_DEBOUNCE ms.
volatile bool btnEdge = false;

static void onButtonPress() {
    static uint32_t lockedUntil = 0;
    uint32_t now = millis();
    if (now < lockedUntil) return;
    lockedUntil = now + 10;
    btnEdge = true;
}

// ─── Setup and loop ──────────────────────────────────────────────────────────
void setup() {
    // SPI bit-bang pins
    pinMode(PA9,  OUTPUT);      // SCL
    digitalWrite(PA9,  LOW);
    pinMode(PA12, OUTPUT);      // MOSI
    digitalWrite(PA12, LOW);

    // PA15 = PNP high-side switch, active LOW enables LED driver VCC
    pinMode(PA15, OUTPUT); 
    digitalWrite(PA15, LOW);

    analogReadResolution(12);
    pinMode(PA2, INPUT_ANALOG);   // Not explicitely needed as arduino core takes over when reading
    pinMode(PF0, INPUT_PULLUP);   // USB sense: LP4068 PG or VBUS
    pinMode(PB5, INPUT_PULLUP);   // LP4068 CHRG: active-low when charging (unconfirmed)

    pinMode(PB1, INPUT_PULLUP);   // Hand-soldered a button to sit where the mouthpiece was
    attachInterrupt(digitalPinToInterrupt(PB1), onButtonPress, FALLING);

    // All LEDs on for 1s on first turnon
    memset(frameDigits, 0xFF, 144);
    memset(frameHalo,   0xFF, 144);
    composeAndSend();
    delay(1000);
    allClear();
}

// Run the selected animation
static void runAnimation(int choice) {
    animSwitchPos = readSwitch();
    switch (choice) {
        case 0:  haloChase(50);          break;
        case 1:  haloCometChase(30);     break;
        case 2:  haloFill(200, 80);      break;
        case 3:  breathe();              break;
        case 4:  barFillUp();            break;
        case 5:  breathe(1, 20, true);   break;
        case 6:  sparkle();              break;
        case 7:  ripple();               break;
        case 8:  fireworks();            break;
        case 9:  heartbeat();            break;
        case 10: meteorShower();         break;
        case 11: raveAnimation();      break;
    }
}
static const int ANIM_COUNT = 12;

int animation_choice = 0;
int counter = 0;
int prev_pos = -1;

void loop() {
    // Switch position is read first so the button state machine can gate on it.
    int switch_position = readSwitch();
    if (prev_pos == -1) {
        prev_pos = switch_position;
    }

    // ── Button state machine ─────────────────────────────────────────────────
    // pressStartMs: set when ISR signals a falling edge; 0 = no active press.
    // holdActive:   true while button is held past the 500 ms threshold.
    // highSince:    when the pin first went HIGH after a press; 0 = not yet.
    // Release is confirmed only after pin has been HIGH for RELEASE_DEBOUNCE ms.
    // animation_choice only advances when the switch is in position 2.
    static uint32_t pressStartMs = 0;
    static bool     holdActive   = false;
    static uint32_t highSince    = 0;
    const  uint32_t RELEASE_DEBOUNCE = 50;

    if (btnEdge) {
        btnEdge      = false;
        pressStartMs = millis();
        highSince    = 0;
    }

    if (pressStartMs) {
        bool pinHigh = (digitalRead(PB1) == HIGH);
        if (pinHigh) {
            if (!highSince) highSince = millis();
        } else {
            highSince = 0;
        }
        bool stillDown = !(highSince && (millis() - highSince >= RELEASE_DEBOUNCE));

        if (stillDown && !holdActive && millis() - pressStartMs >= 500) {
            holdActive = true;
        }
        
        // Hold: all LEDs on at full brightness
        //       battery info displayed on digits (top = percent, bottom = voltage)
        if (holdActive) {
            if (switch_position != 3) {
                memset(frameDigits, 0xFF, 144);
                haloClear();  // halo=0 so OR-compose doesn't re-light cleared digit bytes
                int rawVref = analogSample(AVREF);
                int pct = readBatteryPercent();
                int v   = rawVref > 0 ? (int)((long)1200 * 4095 / rawVref / 100) : 0;
                setDigitBytes(0, pct >= 100 ? 1 : 0);   // top hundreds
                setDigitBytes(2, (pct / 10) % 10);      // top tens
                setDigitBytes(3, pct % 10);             // top ones
                setDigitBytes(1, v >= 100 ? 1 : 0);     // bottom hundreds
                setDigitBytes(4, (v / 10) % 10);        // bottom tens
                setDigitBytes(5, v % 10);               // bottom ones
                composeAndSend();
            } else {
                counter = 0;
                digitsClear();
                displayNumber(true, 0);
                composeAndSend();
            }
            if (!stillDown) {
                holdActive   = false;
                pressStartMs = 0;
                highSince    = 0;
                allClear();
                composeAndSend();
            }
            return;
        }

        if (!stillDown) {
            if (switch_position == 2) {
                animation_choice = (animation_choice + 1) % ANIM_COUNT;
            } else if (switch_position == 3) {
                counter = counter + 1;
            }
            pressStartMs = 0;
            highSince    = 0;
        } else {
            return;
        }
    }

    if (switch_position == 1) {
        // Sleep/low power mode
        prev_pos = 1;
        sleepDisplay();
        // __WFI() halts the CPU until the next SysTick interrupt (~1 ms),
        // cutting active-run current without requiring STOP-mode wakeup config.
        while (readSwitch() == 1) {
            if (btnEdge) {
                btnEdge = false;
                wakeDisplay();
                uint32_t pressedAt = millis();
                uint32_t hs        = 0;
                bool     holdFired = false;

                // Poll until released (debounced) or switch moves.
                // Once held past 500 ms, show battery status.
                while (readSwitch() == 1) {
                    bool pinHigh = (digitalRead(PB1) == HIGH);
                    if (pinHigh) { if (!hs) hs = millis(); }
                    else         { hs = 0; }
                    bool released = hs && (millis() - hs >= RELEASE_DEBOUNCE);

                    if (!holdFired && millis() - pressedAt >= 500) {
                        holdFired = true;
                        memset(frameDigits, 0xFF, 144);
                        haloClear();
                        int rawVref = analogSample(AVREF);
                        int pct = readBatteryPercent();
                        int v   = rawVref > 0 ? (int)((long)1200 * 4095 / rawVref / 100) : 0;
                        setDigitBytes(0, pct >= 100 ? 1 : 0);
                        setDigitBytes(2, (pct / 10) % 10);
                        setDigitBytes(3, pct % 10);
                        setDigitBytes(1, v >= 100 ? 1 : 0);
                        setDigitBytes(4, (v / 10) % 10);
                        setDigitBytes(5, v % 10);
                        composeAndSend();
                    }
                    if (released) break;
                    delay(5);
                }

                if (holdFired) {
                    allClear();
                    composeAndSend();
                } else {
                    // Short press — show animation preview without advancing choice.
                    runAnimation(animation_choice);
                    allClear();
                    composeAndSend();
                    btnEdge = false;
                }
                sleepDisplay();
            }
            __WFI();
            delay(50);
        }
        wakeDisplay();
        return;

    } else if (switch_position == 2) {
        // Animation preview and select mode
        if (prev_pos == 3) {
            digitsClear();
            composeAndSend();
        }
        prev_pos = 2;
        displayNumber(true, animation_choice);
        runAnimation(animation_choice);

    } else if (switch_position == 3) {
        // Basic counter utility mode
        prev_pos = 3;
        int rawVref = analogSample(AVREF);
        int v       = rawVref > 0 ? (long)analogSample(PA2) * 12 / rawVref : 0;  // tenths of a volt

        digitsClear();
        displayNumber(true, counter % 200);
        displayNumber(false, floor(counter/200));
        composeAndSend();
        delay(50);
    }

    
}
