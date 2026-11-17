# Lightning Bugs

Goal: sync multiple Geek Bar Pulse X Jam devices (PY32F030EK28) to a computer for a shared time base, then run LED effects on a common tempo/cadence.

This document is an initial feasibility assessment. Hardware details come from general PY32F030 family knowledge plus the existing firmware in `../PY32F030EK28 - Geek Bar Pulse X Jam/`. **Verify pin alternate functions and clock specs against the reference manual and datasheet in that directory before committing to a design.**

## Short answer

Yes. The MCU can react to external signals while running (the existing firmware already does: the PB1 button is a falling-edge interrupt, see `attachInterrupt(... onButtonPress, FALLING)` in `PY32F030EK28.ino`). It has several hardware timers. The real limit is **clock accuracy**: free-running, it drifts too much for long-term sync, so periodic resync is needed.

## Taking in signals while running

- **EXTI (pin interrupts):** any GPIO can trigger an interrupt on a rising or falling edge, as PB1 does now. A "beat" pulse from a master into a spare pin (or PB1) is the simplest hardware sync.
- **Timer input capture:** TIM1, TIM3, TIM14, TIM16 and TIM17 can timestamp an edge in hardware to within a clock cycle (~20–40 ns). More precise than reading `millis()` in an ISR, and it lets you measure the master's period exactly.
- **USART1/2:** a serial link for sending tempo, phase or commands. Note: the PY32F030 has **no USB peripheral**, so the USB-C port can't act as a serial device to a computer. Only SWD is routed to the port (USB-C A5/B5 → PA13/PA14).

## Getting time from a computer with no hardware changes: SWD

A Pico debug probe is already used for flashing over SWD. On Cortex-M0+, a debugger can **read and write RAM while the core keeps running**, so pyocd can serve as the sync channel:

1. The HAL millisecond counter `uwTick` is at `0x200002f8` in the current build (see `PY32F030EK28.ino.map`). This address can move when code changes, so look it up in the `.map` each time, or put dedicated `volatile` sync variables in a fixed linker section.
2. On the host: record host time, `target.read32()` the tick counter, record host time again. Take the midpoint (NTP-style). Repeat several times and keep the sample with the shortest round trip. This gives the clock offset, typically within ~1–2 ms.
3. Repeat over a few minutes to measure each unit's **drift rate**.
4. `write32()` the offset, rate correction and tempo/epoch into a RAM variable. Persist the rate correction to flash if it should survive power loss.

Limitation: this only works while the device is plugged in; afterwards it runs free.

**Caution:** don't repurpose PA13/PA14 as a UART without a recovery plan (e.g. a boot-time delay before remapping, or connect-under-reset). Otherwise SWD access can be lost.

## Timekeeping hardware and accuracy

| Source | Notes |
|---|---|
| **HSI (internal RC, 24 MHz)** | Drives `millis()`/`micros()` and all timers. Factory-trimmed to ~±1% at room temperature, a few % over the temperature range. |
| **HSI trim bits (RCC_ICSCR)** | Oscillator frequency can be adjusted at runtime, allowing correction against the master. |
| **LSI (~32 kHz)** | Low power, poor accuracy (±10% or worse). Not suitable for timing. |
| **LSE (32.768 kHz crystal)** | Supported by the chip, but this board almost certainly has no crystal fitted. |
| **RTC** | HAL RTC code is already linked in the build. Without an LSE it runs on LSI, so it's no better. |
| **LPTIM, SysTick** | Useful for low-power wakeups (e.g. "fire at time T" while in sleep mode). |

In practice: at 120 BPM, 1% error is 5 ms per beat, so two devices can drift a full beat apart in under a minute. Mitigations:

- **Per-unit calibration:** measuring drift over SWD as above typically reduces error to ~0.05–0.1% at stable temperature, giving tens of minutes before drift is noticeable.
- **Regular resync** to correct the remainder: a wired pulse, a serial message, or an added wireless input (IR receiver or light sensor on a spare pin, read via timer input capture).
- **Schedule against absolute times, not `delay()`.** The current animations chain `delay(stepMs)` calls, so error accumulates every step. For synced effects, compute `nextBeat = epoch + n * period` (corrected by the per-unit rate) and wait until `(int32_t)(millis() - nextBeat) >= 0`. The existing firmware already uses this pattern for its hold timers.

## Layout

```
lightning_bugs/
├── host/
│   ├── lb_sync.py          pyocd sync tool (list / sync / status / hold / release)
│   └── test_lb_sync.py     simulated-device tests (no hardware needed)
└── firmware/lightning_bugs/
    ├── lb_sync.h           sync block, master clock, beat grid, boot guard
    ├── lightning_bugs.ino  example: beat-synced LED patterns
    └── matrix_map.h        LED map (copied from the main firmware)
```

## How sync works

1. The firmware keeps a small **sync block** in RAM, tagged with a magic number. `lb_sync.py` attaches over SWD in `attach` mode (no halt, no reset, `auto_unlock` off so it can never mass-erase) and finds the block by scanning RAM, so its address can change between builds.
2. `sync` reads the chip's `millis()` counter (`uwTick`) every 5 s for 10 min. Each sample is the fastest of 8 reads, timestamped at the midpoint of the round trip. A least-squares fit gives the chip's clock rate against the host's.
3. The host writes back an **anchor** (local tick ↔ Unix µs), a **rate correction** in parts per billion, and the **beat grid** (epoch + period). A sequence counter keeps the firmware from adopting a half-written block, and the firmware acknowledges the new sync.
4. The firmware computes master time from `millis()` using the same integer formula the host uses to check it:
   `master_us = anchor_us + L*1000 + L*corr_ppb/1e6`, with `L = millis() − anchor_tick`.
5. Effects are **scheduled against absolute beat times** (`lbWaitUntil(lbBeatTime(n))`), never chained `delay()`s. Each beat's pattern is computed from the beat number alone, so every device shows the same thing at the same moment.

Beat `n` falls at Unix time `epoch + n × period`. Every device synced against an NTP-disciplined computer shares that timeline, so you can sync devices **one at a time with a single probe**, even on different days, as long as `--bpm` and `--epoch` match.

## Build and flash wrapper

First-time setup: in a `claude_sandbox` session nothing needs running by hand. The root `claude_sandbox_deps.yaml` installs `python3-venv` and `libusb` (apt) and runs `tools/setup.sh` at every launch (no root; it installs the pinned `arduino-cli`, the py32duino core and toolchain, and the pyocd venv, and is quick when already done). Then `export PATH="$HOME/.local/bin:$PWD/.venv/bin:$PATH"`. On your own machine the script refuses to run unless you pass `--i-know-this-modifies-my-system`; it then keeps everything under `lightning_bugs/.tools/` (git-ignored) and `.venv`, never touches `~/.local/bin`, `~/.arduino15` or your arduino-cli config, writes only pip's and pyocd's package caches outside the repo, and prints the `PATH` and `ARDUINO_DIRECTORIES_*` exports to use afterwards (Linux only; `lb_flash.py` honours `ARDUINO_DIRECTORIES_DATA`). See `assessments/toolchain.md`.

`tools/lb_flash.py` implements step 3 of `assessments/swd-recovery.md`. Needs `arduino-cli` (with the py32duino core) and `pyocd`.

```sh
python3 tools/lb_flash.py check                          # source safety scan only
python3 tools/lb_flash.py [--fqbn <board>] build         # check + compile + binary check
python3 tools/lb_flash.py -u <probe> dump                # back up the unit's flash BEFORE flashing it
python3 tools/lb_flash.py -u <probe> flash --canary      # flash a canary unit, verify SWD
python3 tools/lb_flash.py -u <probe> flash               # sealed unit: only canary-tested builds
```

`dump` reads the 64 KB of flash (`0x08000000`) twice over SWD without halting or resetting the chip, and saves it to `backups/dump_<time>_<sha>.bin` (git-ignored; copy it somewhere durable) only if both reads are identical and not all `0x00`/`0xFF` (a read-protected chip can look like that, and such a dump is not a backup). It never overwrites a file. `--output` picks the file and `--size` the length. It does not stop `flash` from running without a backup. (`pyocd read`, which an old comment in `PY32F030EK28.ino` suggests, does not exist in the pinned pyocd.)

It refuses to build if the sketch mentions PA13/PA14, raw GPIOA mode/AF writes, STOP/STANDBY, deep-sleep bits, flash/option-byte access, RCC clock changes or DBGMCU (waive one line with `// lb-allow-swd-risk`). After building it checks the ELF for forbidden HAL symbols and the `.bin` for flash-unlock keys. After flashing it resets the chip and confirms it can reattach over SWD in the guard, after the guard, and 30 s later. The `--canary` flag is your declaration that the unit is recoverable; builds that pass are recorded by hash in `.lb_canary.json` (git-ignored). The default `--fqbn` is `PY32Duino:PY32:GenF030:pnum=PY32F030x8`.

## Debug probe

The supported probe is a Raspberry Pi Pico running debug-probe (CMSIS-DAP) firmware (USB `2e8a:000c`), used
through pyocd's built-in driver. Nothing needs configuring: with one probe attached pyocd picks it. To be
explicit (or with several probes), find its ID with `python3 host/lb_sync.py list` (or `pyocd list`) and pass
`--probe <id>` / `-u <id>` to `lb_flash.py` and `lb_sync.py`. They do not know what kind of probe it is.

### Wiring the Pico to the unit

Sources: the prior-art project in `PY32F030EK28 - Geek Bar Pulse X Jam/README.md`, the schematic of the matching
board (schlae/VapeRE `BD0061`, `BD0061.kicad_sch`: PY32F030K2, USB-C `J1`) and dwaskevich/Geek_Bar_Pulse_hijack (same
maker, J-Link). **Not yet tried on our canary:** treat it as a starting point and check it with `pyocd list` and
`lb_flash.py dump` before anything else.

The unit's SWD pins (PA13 SWDIO, PA14 SWCLK) are brought out to the USB-C port's **A5 and B5** (the CC pins), so
the case does not need opening. Use a USB-C breakout board and wire:

```
SWCLK: Pico GP2 -> ~240 ohm -> B5 -> PA14
SWDIO: Pico GP3 -> ~240 ohm -> A5 -> PA13
GND:   Pico GND -> USB-C A12 (B12 is also GND)
(prior art also pulls both lines up to 3.3V with 10k; see below)
```

Per the VapeRE schematic, **GND is A12 and B12**, VBUS is A9/B9, and the SWD lines are on the CC pins, each with a
5.1k resistor to ground (R1, R2). In its drawing SWDIO is on B5 and SWCLK on A5 (read from the KiCad file, so
verify with a meter); the Jam prior art wires them the other way round. Both are right for one plug orientation,
so if it does not connect, swap the two signal wires (or flip the connector) before suspecting anything else.

- GP2 = SWCLK and GP3 = SWDIO are the Pico debug-probe firmware's default pins (`debugprobe` v2.3.1,
  `include/board_pico_config.h`). GP1 is its target-reset (nRESET) output, unused here.
- The series resistors are there because the Pico drives 3.3 V while the unit runs at battery voltage (up to ~4.2 V,
  ~5 V on USB).
- Power the unit from its own battery. Do not connect the Pico's VBUS/VSYS to the unit, and do not plug a charger
  or USB host into the breakout while the probe is wired to A5/B5 (their CC lines would drive the SWD pins).
- **The unit sleeps, and SWD is unavailable while it does** (hijack README: normally in deep sleep or stop; the slide
  switch wakes it and opens a "small connect window", and plugging in a charger opens another). Run the probe command
  in a retry loop, then move the switch, so an attempt lands in the window. `dump` reads the flash twice, which needs
  the link to stay up the whole time; a very slow `--frequency` stretches that, so do not go lower than needed.
  The 500 kHz default is the speed hijack's own J-Link script uses (`speed 500`).
- The unit's 5.1k CC pull-downs (R1/R2 above, "5.1k pull-downs on CC1/CC2" in hijack) are on a stock unit, which is
  why the Jam author removed theirs. A 10k pull-up to 3.3 V against a 5.1k pull-down only divides to about 1.1 V,
  so the external pull-ups cannot lift an idle line to a logic high while those resistors are present.
  Whether the link works with them in place is untested here.
- The Pico has no target-voltage input: it always drives 3.3 V. hijack's J-Link needed its VTref set to 3300 mV by
  hand for the same reason (unit runs from the battery, about 3.3 to 4.2 V).
- Pull-ups: debugprobe v2.3.1 enables the RP2040's internal pull-up on SWDIO only (`gpio_pull_up(PROBE_PIN_SWDIO)`
  in `probe.pio`); SWCLK is an actively driven output with none. That internal pull-up is weak (tens of kilohms), so
  the prior art's external 10k pull-ups are stronger, not built in. The Jam prior art removed the unit's own
  pull-downs on A5/B5 (it recalls 2.5k; the schematic and hijack say 5.1k) but says that is probably unnecessary.
- Take a backup first: `python3 tools/lb_flash.py -u <probe> dump`.
- A similar chip's author needed resistors, a slower clock and a one-off `edbg` wake-up to connect; see
  `assessments/py32c642-prior-art.md` (untried on our unit).

## Usage

```sh
pip install pyocd                       # plus the Puya pack that provides py32f030x8
python3 host/lb_sync.py list            # find your probe ID
python3 host/lb_sync.py -u <probe> sync --bpm 120
python3 host/lb_sync.py -u <probe> status
```

Recommended workflow for the 4–6 hour target:

1. `sync` (10 min). Run it **on battery, at the temperature the device will be used at**. If you can, wire only SWDIO/SWCLK/GND so USB VBUS isn't powering the board: the internal oscillator shifts with supply voltage.
2. Unplug and leave the device running in deployment-like conditions for a few hours.
3. Plug back in and run `sync --refine`. It prints how far the device drifted, then re-measures the rate using the whole period since the last sync as its baseline. That is far more precise than a 10-minute window, and it captures the device's real operating conditions.
4. Run `status` at any time to see the current offset in ms. Checking it at the end of a session is the only real measure of how well sync held up.

### Boot guard

`lbBootGuard()` parks the firmware for 3 s at power-up (a single halo LED spins). **Anything that could cut off SWD, such as remapping PA13/PA14, STOP mode or clock changes, must run after it.** To recover a device whose firmware breaks SWD:

```sh
python3 host/lb_sync.py -u <probe> hold --wait 60   # then power-cycle the device
python3 host/lb_sync.py -u <probe> hold --reset     # if SWD still works: reset into the guard
# device sits in the guard (center LEDs lit) → reflash with pyocd as usual
python3 host/lb_sync.py -u <probe> release
```

Power-cycling means disconnecting the battery, since the slide switch doesn't cut power to the MCU.

## What accuracy to expect (read this)

The PY32 has no crystal, so the clock is an RC oscillator (HSI). Calibration removes its **fixed** error. Over 4–6 hours, what's left is how much the oscillator **changes**:

| Source of error | Typical size | Drift over 6 h |
|---|---|---|
| Measurement (10-min `sync`) | ~0.2 ppm | ~5 ms (simulated) |
| Measurement (`--refine` after 3 h) | ~0.2 ppm | ~5 ms |
| Temperature change of a few °C | likely tens to hundreds of ppm* | ~0.2 s to several s |
| Battery voltage sagging over the session | likely tens of ppm* | ~0.1 to 1 s |

\* These are estimates from typical internal-RC behavior, not measured on this chip. Check against the datasheet and against `status` results.

So **"roughly in sync" (within a fraction of a second) for 4–6 h unplugged is plausible if temperature is stable**, such as devices sitting indoors. It is not plausible if some are in pockets and others on a table. If `status` shows drift is too large, the next steps are, in order:

1. Calibrate under the real conditions (`--refine`, as above).
2. Add a periodic resync input (IR or light sensor on a spare pin, read by timer input capture), which corrects drift continuously.
3. Fit a 32.768 kHz crystal (LSE). This needs a board with the pads and the right pins free; a ±20 ppm crystal still drifts about 0.4 s in 6 h before calibration.

## Status

- [x] Firmware sync block, master clock, beat grid, boot guard (`lb_sync.h`)
- [x] Host sync tool with offset/rate measurement, `--refine`, `status`, `hold`/`release`
- [x] Example beat-synced sketch
- [x] Host logic tested against a simulated device (`python3 -m unittest host/test_lb_sync.py`)
- [x] Compiles with py32duino 0.1.3: 13.3 KB of 64 KB flash, 1.4 KB of 8 KB RAM
- [ ] **Not yet run on hardware.** Check that `uwTick` is the counter behind `millis()` (it is linked; the tool refuses to sync if the counter isn't ~1 kHz).
- [ ] Measure real drift over 4–6 h with `status`, and replace the estimates above with measured numbers
- [ ] Optional: store the rate correction in flash so it survives a reboot
- [ ] Optional: hardware resync input
