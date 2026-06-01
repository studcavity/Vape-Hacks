#pragma once
#include <stdint.h>
#include <stdbool.h>

// LED frame: 144 bytes, ONE BYTE PER LED (byte-addressed, not bit-packed).
// Non-zero byte = LED on, 0x00 = LED off.
// We write bit 3 (value 0x08) for "on" via setBitBuf — any non-zero value works.
// Sentinel: byteIdx = 0xFF (unused slot, out of range 0..143).
struct Segment { uint8_t byteIdx; uint8_t bitIdx; };

// ─── Digit segment map ───────────────────────────────────────────────────────
// Segment order per digit: A(top), B(upper-R), C(lower-R), D(bot), E(lower-L), F(upper-L), G(mid)
// Digits 0,1 are partial (B and C only — "1" in hundreds place)
// Layout in frame (confirmed by disassembly):
//   Row 0 (top):    [0] [digit2 0-6] [7] [digit3 8-14] [15]   → 0..199
//   Row 1 (bottom): [16] digit4 16-22] [23] [digit5 24-30] [31] → 0..199
static const Segment DIGIT_SEG[6][7] = {
    // digit 0 — partial top-left  (only B=7, C=15)
    {{0xFF,0xFF}, { 7,3}, {15,3}, {0xFF,0xFF}, {0xFF,0xFF}, {0xFF,0xFF}, {0xFF,0xFF}},
    // digit 1 — partial bottom-left  (only B=23, C=31)
    {{0xFF,0xFF}, {23,3}, {31,3}, {0xFF,0xFF}, {0xFF,0xFF}, {0xFF,0xFF}, {0xFF,0xFF}},
    // digit 2 — top tens   (bytes 0–6)
    {{ 0,3}, { 1,3}, { 2,3}, { 3,3}, { 4,3}, { 5,3}, { 6,3}},
    // digit 3 — top ones   (bytes 8–14)
    {{ 8,3}, { 9,3}, {10,3}, {11,3}, {12,3}, {13,3}, {14,3}},
    // digit 4 — bottom tens (bytes 16–22, start=0x10 in firmware)
    {{16,3}, {17,3}, {18,3}, {19,3}, {20,3}, {21,3}, {22,3}},
    // digit 5 — bottom ones (bytes 24–30, start=0x18 in firmware)
    {{24,3}, {25,3}, {26,3}, {27,3}, {28,3}, {29,3}, {30,3}},
};

// ─── 7-segment encoding ──────────────────────────────────────────────────────
// Segment order: A  B  C  D  E  F  G
static const bool NUMBER_TABLE[10][7] = {
    {1,1,1,1,1,1,0}, // 0
    {0,1,1,0,0,0,0}, // 1
    {1,1,0,1,1,0,1}, // 2
    {1,1,1,1,0,0,1}, // 3
    {0,1,1,0,0,1,1}, // 4
    {1,0,1,1,0,1,1}, // 5
    {1,0,1,1,1,1,1}, // 6
    {1,1,1,0,0,0,0}, // 7
    {1,1,1,1,1,1,1}, // 8
    {1,1,1,1,0,1,1}, // 9
};

// ─── Halo ring ───────────────────────────────────────────────────────────────
// 16 LEDs, bytes 33–48, in physical clockwise order (extracted from firmware tables)
// [0..12] = circular ring (bytes 33–45)
// [13..15] = center cluster (bytes 48,47,46)
static const uint8_t HALO_MAP[] = {
    33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 48, 47, 46
};
static const int HALO_COUNT        = 16;
static const int HALO_RING_COUNT   = 13;  // circular ring only
static const int HALO_CENTER_COUNT =  3;  // center cluster only

// ─── Outer ring LEDs ─────────────────────────────────────────────────────────
// ~50 outer decorative LEDs in clockwise order (from firmware animation table at 0x7700).
static const uint8_t OUTER_SWEEP[] = {
    76, 78, 79, 80, 81, 74, 72, 70, 69, 71, 67, 66, 65, 63, 62,
    116, 117, 118, 124, 125, 126, 132, 127, 133, 139, 140, 141, 142, 143,
    111, 112, 113, 114, 115,
    109, 108, 106, 105, 104, 103, 107,
    97, 100, 102, 95, 99, 84, 94, 83, 75,
};
static const int OUTER_SWEEP_COUNT = 50;

// ─── Watt/level bar groups ───────────────────────────────────────────────────
// 10 level groups extracted from firmware table at 0x764B.
// Each group is the LEDs that light at that bar level (cumulative fill).
// Sentinel 0xFF terminates each group.
static const uint8_t BAR_LEVELS[10][16] = {
    {83, 84, 85, 86, 116, 117, 118, 119, 92, 93, 94, 0xFF},           // level 0
    {104, 0xFF},                                                         // level 1
    {97, 98, 99, 100, 101, 102, 80, 81, 82, 70, 71, 72, 0xFF},        // level 2
    {91, 0xFF},                                                          // level 3
    {78, 77, 76, 59, 60, 61, 64, 65, 66, 67, 0xFF},                   // level 4
    {52, 51, 0xFF},                                                      // level 5
    {56, 57, 0xFF},                                                      // level 6
    {109, 110, 111, 106, 107, 108, 113, 114, 115, 122, 123, 0xFF},    // level 7
    {127, 128, 129, 130, 131, 132, 137, 138, 0xFF},                    // level 8
    {140, 141, 142, 134, 135, 0xFF},                                    // level 9
};

// ─── Left / right column LEDs (watt meter) ───────────────────────────────────
// Each column has 20 LEDs going top-to-bottom on that side of the display.
static const uint8_t LEFT_COL[20]  = {95,88,89,75,74,73,68,62,54,121,126,96,103,87,90,79,69,63,58,55};
static const uint8_t RIGHT_COL[20] = {96,103,87,90,79,69,63,58,55,53,50,105,112,120,125,124,133,143,139,136};

// ─── Extra LEDs (icons + bar/column LEDs not in OUTER_SWEEP or HALO_MAP) ─────
// Byte 32  = lightning bolt icon (above top digit row).
// Byte 49  = blob icon (below bottom digit row).
// Bytes 50–138: bar-level indicator LEDs and left/right column LEDs that do
//   not appear in OUTER_SWEEP;
static const uint8_t EXTRA_LEDS[] = {
    32, 49,                                              // icon LEDs
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61,    // bar + column (50–61)
    64, 68, 73, 77, 82,                                  // bar lvl 4 + left col
    85, 86, 87, 88, 89, 90, 91, 92, 93,                 // bar lvls 0–3 + cols
    96, 98, 101, 110,                                    // column + bar lvl 2/7
    119, 120, 121, 122, 123,                             // bar lvl 0 + columns
    128, 129, 130, 131, 134, 135, 136, 137, 138,        // bar lvls 8–9 + col
};
static const int EXTRA_COUNT = 46;

// ─── Breathing animation ─────────────────────────────────────────────────────
// Cosine ramp: 256 steps, 0→255→0.  Generated from (1-cos(i*π/128))/2*255.
static const uint8_t BREATHE_TABLE[256] = {
      0,   0,   0,   0,   1,   1,   1,   2,   2,   3,   4,   5,   5,   6,   7,   9,
     10,  11,  12,  14,  15,  17,  18,  20,  21,  23,  25,  27,  29,  31,  33,  35,
     37,  40,  42,  44,  47,  49,  52,  54,  57,  59,  62,  65,  67,  70,  73,  76,
     79,  82,  85,  88,  90,  93,  97, 100, 103, 106, 109, 112, 115, 118, 121, 124,
    127, 131, 134, 137, 140, 143, 146, 149, 152, 155, 158, 162, 165, 167, 170, 173,
    176, 179, 182, 185, 188, 190, 193, 196, 198, 201, 203, 206, 208, 211, 213, 215,
    218, 220, 222, 224, 226, 228, 230, 232, 234, 235, 237, 238, 240, 241, 243, 244,
    245, 246, 248, 249, 250, 250, 251, 252, 253, 253, 254, 254, 254, 255, 255, 255,
    255, 255, 255, 255, 254, 254, 254, 253, 253, 252, 251, 250, 250, 249, 248, 246,
    245, 244, 243, 241, 240, 238, 237, 235, 234, 232, 230, 228, 226, 224, 222, 220,
    218, 215, 213, 211, 208, 206, 203, 201, 198, 196, 193, 190, 188, 185, 182, 179,
    176, 173, 170, 167, 165, 162, 158, 155, 152, 149, 146, 143, 140, 137, 134, 131,
    128, 124, 121, 118, 115, 112, 109, 106, 103, 100,  97,  93,  90,  88,  85,  82,
     79,  76,  73,  70,  67,  65,  62,  59,  57,  54,  52,  49,  47,  44,  42,  40,
     37,  35,  33,  31,  29,  27,  25,  23,  21,  20,  18,  17,  15,  14,  12,  11,
     10,   9,   7,   6,   5,   5,   4,   3,   2,   2,   1,   1,   1,   0,   0,   0,
};

// Rave animation
static const uint8_t RAVE_SWEEP[144] = {
    // 0–15: top digit row — segments A,B,C,D,E,F,G of left digit + sep + right digit + sep
        3, 5, 5, 3, 1, 1, 3, 7,  11,13,13,11, 9, 9,11,15,
    // 16–31: bottom digit row (same x layout)
        3, 5, 5, 3, 1, 1, 3, 7,  11,13,13,11, 9, 9,11,15,
    // 32: unused slot
    0xFF,
    // 33–45: halo ring (clockwise from ~12 o'clock)
        8, 9,11,11,11,10, 8, 7, 6, 5, 5, 6, 7,
    // 46–48: halo center cluster
        8, 8, 8,
    // 49: unused; 50–61: bar (levels 4–6) + left/right column LEDs
    0xFF,13, 7, 8,14, 1, 7, 7, 8, 7, 3, 3, 4,
    // 62–75: left outer arc + bar (64) + left column (68, 73)
        0, 0, 1, 1, 1, 2, 0, 1, 1, 1, 2, 1, 2, 2,
    // 76–90: upper outer arc + bar + column LEDs (87,88,89,90)
        4, 5, 4, 4, 5, 6, 6, 2, 2, 3, 3, 5, 4, 4, 5,
    // 91–103: bar zone + outer arc + right column (96)
        5, 6, 6, 2, 3,13, 4, 4, 4, 4, 5, 5, 6,
    // 104–115: bottom outer arc
        7, 7, 8, 8, 9,10,10,11,11,12,13,13,
    // 116–133: right outer arc + bar + column LEDs (120, 121)
    13,14,14,13,12,13, 9, 9,14,14,15,15,14,14,13,13,15,15,
    // 134–143: far-right outer + bar + right column (136)
    13,13,14,14,14,15,15,14,13,13,
};