---
name: project-geekbar-pulse-x-jam
description: "Full project context for GeekBar Pulse X Jam vape device firmware replacement — hardware, RE findings, protocol, LED map, battery measurement, code architecture"
metadata: 
  node_type: memory
  type: project
  originSessionId: e930cfc4-c57a-4bbf-b945-e88176aa5b2b
---

# GeekBar Pulse X — Custom Firmware Project

**Why:** Replace OEM PY32F030EK28 firmware with developer-friendly code that gives full control of the PLS916H LED matrix while preserving all display behaviors (7-seg digits, halo ring, outer ring, bar levels, icons).

**How to apply:** Use this as the primary reference before touching any code in this project. Verify specifics against current file state before acting on them.

---

## Hardware

### MCU: Puya PY32F030EK28
- ARM Cortex-M0+, 48-pin LQFP
- 64 KB Flash at `0x08000000`, 8 KB RAM at `0x20000000`
- 12-bit ADC, internal Vrefint ≈ 1.2V (spec range 1.14–1.28V; actual chip may differ — see Battery section)
- Toolchain: Arduino IDE with py32duino board support (Generic PY32F030 Kxx variant)
- Debug/flash: Pi Pico running Picoprobe (CMSIS-DAP) via SWD, OpenOCD

### Display driver: PLS916H
- SPI, bit-banged on **PA9 = SCK**, **PA12 = MOSI**
- LED driver VCC enabled by **PA15** (PNP high-side transistor, active-LOW — `digitalWrite(PA15, LOW)` powers the display)

### Power / IO
| Signal | Pin | Notes |
|--------|-----|-------|
| SCK | PA9 | bit-bang SPI |
| MOSI | PA12 | bit-bang SPI |
| LED VCC enable | PA15 | PNP, active-LOW |
| Switch sense | PA2 | 3-position switch (see below) |
| Button | — | interrupt-driven, FALLING edge ISR sets `volatile bool btnEdge` |
| USB present | PF0 | HIGH = USB power |
| Charge in progress | PB5 | open-drain, LOW = charging (LP4068 CHRG pin) |
| Vrefint (ADC) | AVREF | internal channel, used for battery voltage |

### Three-position switch (PA2 ADC)
- **Position 1 (left/sleep):** PA2 shorted to GND → ADC reads < 20 counts → sleep mode
- **Position 2 (middle/active):** PA2 at VDDA → ADC reads > 2000 counts → main animation mode
- **Position 3 (right/battery display):** PA2 at mid-rail → ADC reads 20–2000 counts
- **Critical:** In position 1, PA2 = GND, so `analogSample(PA2)` returns ~0. Any voltage formula using PA2 will read 0 in pos 1.

---

## Reverse Engineering Findings

### Original firmware binary
- Full flash dump available as `backup_flash_full.bin` / `.s` (disassembly)
- Flash size: 64 KB starting `0x08000000`

### SPI protocol (161-byte frame)
Extracted from disassembly + confirmed against community research (sm2013-vapehack/geekbar_pulse_x_screen_reuse):
1. **Header (13 bytes):** `{0x5A,0xFF,0x01,0x5A,0x24,0x21,0x3D,0x01,0x83,0x5A,0xFF,0x02,0x5B}`
2. **LED data (144 bytes):** byte-addressed; `0x00` = off, any non-zero = on (driver supports 8-bit grayscale, but we use `0xFF` for on)
3. **Checksum (1 byte):** 8-bit sum of the 144 data bytes (wraps)
4. **Tail (4 bytes):** `{0x5A,0xFF,0x04,0x5D}`
5. **Termination pulse:** ~3 µs CLK pulse at 200 kHz (bit-bang 2–3 edges) after packet

SPI parameters: Mode 0 (CPOL=0, CPHA=0), ~1 MHz, MSB first.

### LED frame layout (144 bytes, indices 0–143)
Confirmed by disassembly of firmware animation/display routines:

**7-segment digit rows:**
```
Row 0 (top):    bytes  0–6  = digit2 (tens),  byte  7 = icon/separator,
                bytes  8–14 = digit3 (ones),  byte 15 = icon/separator
Row 1 (bottom): bytes 16–22 = digit4 (tens),  byte 23 = icon/separator,
                bytes 24–30 = digit5 (ones),  byte 31 = icon/separator
```
Segment order per digit: **A(top), B(upper-R), C(lower-R), D(bot), E(lower-L), F(upper-L), G(mid)**

**Partial "hundreds" digits (only B and C segments used):**
- Digit 0 (top-left "1"): B=byte 7, C=byte 15
- Digit 1 (bottom-left "1"): B=byte 23, C=byte 31

**Halo ring:** bytes 33–48
- `HALO_MAP[] = {33,34,35,36,37,38,39,40,41,42,43,44,45,48,47,46}` (clockwise)
- 13 ring LEDs (bytes 33–45), 3 center cluster (bytes 48,47,46)

**Icon LEDs:**
- Byte 32 = lightning bolt icon (above top digit row)
- Byte 49 = blob icon (below bottom digit row)

**Outer ring (decorative, ~50 LEDs clockwise from firmware table at 0x7700):**
See `OUTER_SWEEP[]` in `matrix_map.h`

**Watt/level bar groups** (from firmware table at 0x764B):
10 groups, sentinel 0xFF terminated. See `BAR_LEVELS[10][16]` in `matrix_map.h`.

**Left/right column LEDs:** 20 each. See `LEFT_COL[20]` and `RIGHT_COL[20]` in `matrix_map.h`.

**Extra LEDs (not in OUTER_SWEEP or HALO_MAP):**
`EXTRA_LEDS[46]` = bytes {32,49, 50–61, 64,68,73,77,82, 85–93, 96,98,101,110, 119–123, 128–131,134–138}
These are bar-level indicator LEDs, left/right column LEDs, and the two icon LEDs.
All full-display animations must include EXTRA_LEDS in addition to OUTER_SWEEP and HALO_MAP/HALO_CENTER.

---

## Critical Code Architecture

### Frame buffers and OR-compose
Two 144-byte buffers: `frameDigits` and `frameHalo`. `composeAndSend()` ORs them into `frameOut` before transmitting.

**OR-compose problem:** If `frameHalo` is `memset(0xFF, 144)` (all-on), then `frameDigits[i] | frameHalo[i] = 0xFF` always — digit segments can never go "off." Solution: use `haloClear()` (zeros frameHalo) and write `0xFF` or `0x00` full-byte values to digit positions in `frameDigits`.

**`haloClear()` vs `memset(frameHalo, 0xFF)`:** Many animations set frameHalo to 0xFF for halo effects. When switching to digit display mode (hold-button, battery display), always call `haloClear()` first.

### Key helper functions
- `setDigitBytes(int d, int val)` — writes full 0xFF/0x00 bytes to all 7 segments of digit d (0–5) for numeral val (0–9). Handles sentinel bytes (byteIdx=0xFF). Handles partial digits 0/1 (only B,C segments).
- `setExtra(uint8_t val)` — sets all EXTRA_LEDS to val (0x00 or 0xFF)
- `haloClear()` — zeros frameHalo
- `animOK()` — returns `!btnEdge && readSwitch() == animSwitchPos`; all animation loops poll this to allow button/switch interruption
- `analogSample(pin, n=5)` — averages n ADC reads; Vrefint requires extra settle-time care (see note in code)

### Animation interruption
`animSwitchPos` captured at animation start in `runAnimation()`. Both button press (`btnEdge` set by FALLING-edge ISR) and switch position change abort any running animation via `animOK()`.

### Button state machine
- Asymmetric debounce: press fires on first falling edge (via `btnEdge`), release confirmed after `RELEASE_DEBOUNCE = 50 ms` of sustained HIGH
- Hold threshold: 500 ms
- `holdActive` flag: set when hold detected, cleared when button releases

---

## Battery Voltage Measurement

### Method
MCU VDD is powered directly from LiPo cell → VDDA = Vbattery. Read Vrefint against VDDA to infer VDDA:
```
Vbattery_mV = VREFINT_MV * 4095 / rawVref
```
where `rawVref = analogSample(AVREF)` and `VREFINT_MV = 1200` (nominal).

### Known calibration issue (discovered in testing)
The PY32F030's actual Vrefint may deviate from nominal 1.2V (spec: 1.14–1.28V). A chip with actual Vrefint ~1.14V will overstate battery voltage by ~5% (e.g., show 4.2V when battery is ~4.0V). **The `1200` constant needs per-chip calibration.**

**Calibration procedure:**
1. Measure actual battery voltage with a multimeter (VBAT+ to GND on PCB)
2. Note `rawVref` from the code (back-calculate from displayed voltage: `rawVref = 1200 * 4095 / (displayed_v_tenths * 100)`)
3. Compute: `actual_vrefint_mv = rawVref * actual_mv_from_multimeter / 4095`
4. Replace `1200` with that value everywhere in the firmware

**Voltage display formula (tenths of volts):**
```cpp
int v = rawVref > 0 ? (int)((long)VREFINT_MV * 4095 / rawVref / 100) : 0;
// v=37 → displays as "3.7"
```
**Do NOT use `analogSample(PA2)` for voltage in position 1** — PA2 is shorted to GND by the switch, giving 0.

### Battery percentage table
Extracted from original firmware at flash `0x08007850`. 20 entries, 5% steps, 3507 mV (0%) → 4075 mV (95%), returns 100% if above all. Stored as `BATT_MV_TABLE[20]` in firmware. EMA smoothing applied inside `readBatteryPercent()` to reduce noise-induced threshold crossings.

---

## Sleep Mode (Position 1) Hold Behavior
- Button held ≥ 500 ms while in position 1 → wake display
- Show: all LEDs on (`memset(frameDigits, 0xFF, 144)` + `haloClear()`) with digit segments overwritten by battery % (top) and voltage in tenths-of-volts (bottom)
- Display layout: digit0=hundreds of %, digit2=tens of %, digit3=ones of %, digit1=hundreds of V, digit4=tens of V, digit5=ones of V
- On button release: clear display, return to low-power sleep loop

---

## Files
| File | Purpose |
|------|---------|
| `pls916h_fw/pls916h_fw.ino` | Main sketch — all state machines, animations, display logic |
| `pls916h_fw/matrix_map.h` | LED index maps: DIGIT_SEG, NUMBER_TABLE, HALO_MAP, OUTER_SWEEP, BAR_LEVELS, LEFT_COL, RIGHT_COL, EXTRA_LEDS, BREATHE_TABLE |
| `backup_flash_full.bin` | OEM firmware binary dump |
| `backup_flash_full.s` | Disassembly (used for RE: GPIO config, SPI protocol, animation tables) |
