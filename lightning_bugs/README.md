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
│   ├── lb_sync.py          pyocd sync tool (list / info / sync / resync / report / status / hold / release)
│   └── test_lb_sync.py     simulated-device tests (no hardware needed)
└── firmware/lightning_bugs/
    ├── lb_version.h        firmware version, build ID stamped by lb_flash.py
    ├── lb_power_policy.h   low-battery rules (pure C, tested natively)
    ├── lb_sync.h           sync block, master clock, beat grid, boot guard, chip UID, die temperature
    ├── lightning_bugs.ino  timed light show (comet chase), dark between shows
    └── matrix_map.h        LED map (copied from the main firmware)
```

## How sync works

1. The firmware keeps a small **sync block** in RAM, tagged with a magic number. `lb_sync.py` attaches over SWD in `attach` mode (no halt, no reset, `auto_unlock` off so it can never mass-erase) and finds the block by scanning RAM, so its address can change between builds.
2. `sync` reads the chip's `millis()` counter (`uwTick`) every 5 s for 10 min. Each sample is the fastest of 8 reads, timestamped at the midpoint of the round trip. A least-squares fit gives the chip's clock rate against the host's.
3. The host writes back an **anchor** (local tick ↔ Unix µs), a **rate correction** in parts per billion, and the **beat grid** (epoch + period). A sequence counter keeps the firmware from adopting a half-written block, and the firmware acknowledges the new sync.
4. The firmware computes master time from `millis()` using the same integer formula the host uses to check it:
   `master_us = anchor_us + L*1000 + L*corr_ppb/1e6`, with `L = millis() − anchor_tick`.
5. Effects are **scheduled against absolute beat times** (`lbWaitUntil(lbBeatTime(n))`), never chained `delay()`s. Each frame is computed from the master time (or beat number) alone, so every device shows the same thing at the same moment.

Beat `n` falls at Unix time `epoch + n × period`. Every device synced against an NTP-disciplined computer shares that timeline, so you can sync devices **one at a time with a single probe**, even on different days, as long as `--bpm` and `--epoch` match.

## Hourly visits: `resync`, the visit log and `report`

The firmware (`lightning_bugs.ino`) plays one show, the stock firmware's halo "comet chase" (about 6 s), at the start of every beat of the grid and keeps the LED panels dark, with the LED driver's power cut, in between. Use the grid as the show cadence: `--every 3600` is a show on every UTC hour (the period is stored in 32 bits of µs, so it can be at most 71 minutes). A unit that is not synced flashes its centre cluster for 0.1 s every 2 s.

First sync of a unit (about 10 minutes), then every time you plug it in:

```sh
python3 host/lb_sync.py sync   --every 3600 --epoch 0     # once per unit, after flashing or a power cycle
python3 host/lb_sync.py resync                            # each visit, about 15 s
python3 host/lb_sync.py report                            # drift statistics so far
```

`resync` uses the anchor the device already holds in RAM from the previous visit as the baseline. The clock rate over the whole interval since then (an hour gives roughly 0.5 ppm resolution, against a few ppm from 10 minutes of sampling) replaces a long measurement; the visit only samples for 10 s to fix the offset. It keeps the device's beat grid unless you pass `--every`/`--bpm`/`--period-ms`/`--epoch`. If the previous visit was less than `--min-baseline` (600 s) ago it only re-anchors and keeps the old rate. A device that has lost power (unsynced) falls back to a full sync (`--no-fallback` makes that an error). The device must have been running continuously since its last sync: a battery disconnect or reset wipes the RAM anchor and `millis()`.

**Device ID.** The firmware copies the chip's factory UID (16 bytes at `0x1FFF0E00`: lot, wafer, die X/Y; reference manual 4.3) into the sync block, so every visit is tied to a physical chip. There is nothing to configure and two units cannot be flashed with the same ID. `status` and `resync` print a short form (`wafer-XYZ`) and the full 32-digit UID is in the log. It is a *chip* ID: it will not tell you which vape in a drawer is which, so note the short ID against a sticker.

**Temperature.** The die temperature sensor is read through the ADC every 10 s while the firmware is idle (never within 0.3 s of a show frame). The sensor is converted with the two factory points `TS_CAL1`/`TS_CAL2` (30 °C and 85 °C at Vref+ = 3.3 V, `0x1FFF0F14/18`) after scaling by the supply voltage seen through VREFINT, since the ADC reference is the battery. The block holds the latest value and the min, max and mean since the last sync was adopted, so each visit logs the temperature *over the interval being measured*, not just at plug-in. This is the die (junction) temperature, so expect it to read a little above the cell and case, and the datasheet gives only ±1–2 °C linearity and ±5 °C at the 30 °C point. For drift data what matters is that it is consistent from visit to visit.

**The log** (`logs/lb_sync_log.jsonl`, git-ignored; `--log` to move it, `--no-log` to skip) gets one JSON line per `sync` and `resync` with: the UID, the drift found at plug-in (`drift_ms`, positive = device ahead), the *raw* clock error over the interval (`raw_rate_ppm`, independent of any correction already applied), the temperature stats, supply voltage, and the correction written. Copy it somewhere durable; it lives only where you ran the tool.

`report` needs no hardware. For each device it prints the mean and spread of the raw rate, the temperature range, a ppm/°C fit (three or more visits) and the residual drift in ms per hour; then, over all devices, the unit-to-unit spread, the temperature coefficient with each unit's own offset removed (`within`), and the naive pooled one. Only visits with a long baseline and a temperature reading are used.

**Battery protection and sleep.** The cell has no protection circuit that we have found, and the MCU's VDD *is* the cell, so the firmware reads the battery from VREFINT (as the stock firmware does) every 10 s while idle and LEDs dark. Once it reads 3.60 V or lower three times running (`lb_power_policy.h`: `LB_LOW_MV`; VREFINT is only ±6 %, so that can be 3.4–3.8 V, still 0.4 V above where damage starts) the unit stops showing, flashes the centre cluster three times, stays awake **60 s** with SWD reachable, and then sleeps in STOP mode (about 6 µA from the datasheet). It wakes when the slide switch (PA2) moves or USB power appears (PF0 rising). Every wake opens another 60 s window and, if the battery is still low, goes back to sleep: one window costs about 7 µAh, so a hundred accidental wakes cost under 0.1 % of the cell. A switch that chatters (more than 4 edges in a window) is ignored for the next sleep and only USB wakes it. With USB power present and the supply above 3.40 V the unit runs normally; below 3.40 V it still sleeps whatever the USB input says (the charger IC does not need the MCU), which also covers a wrongly guessed PF0 polarity.

STOP freezes `millis()`, so a unit that has slept is **unsynced**: after charging, run a full `sync` (`resync` does that for you). `status` and `resync` print the supply voltage, the USB input level, whether low-battery is latched and how many times it has woken; the visit log keeps them (`vcc_mv`, `low_battery`, `usb_input`, `wake_count`), and `report` fits each unit's supply trend over the visits that were not on a charger and gives a rough days-to-3.60 V (the cell's curve is flat in the middle, so it is optimistic early and pessimistic late). To measure battery life, plug each unit in about hourly as above and let the log accumulate.

> **Before flashing a sealed unit with this firmware, on the canary (open) unit:** (1) with `status`, plug and unplug USB and confirm the "USB input" reading follows it (high = plugged); the stock-firmware comment says high, but the disassembly note on when the stock firmware sleeps hints at the opposite, and the 3.40 V floor is the only protection if it is wrong; (2) move the slide switch through its three positions and check each wakes the unit from sleep, with the unit's PA2 level and bias unknown (it is read as analog by the stock firmware, and mid-rail may sit on the digital threshold); (3) after a wake, check that SWD answers and that `millis()` runs at the right rate (the manual says the HSI is selected on exit; its frequency after exit is not verified); (4) drive it below 3.60 V with a bench supply to see it latch, blink and sleep, and note the current in sleep with a meter. If STOP misbehaves the unit cannot be reached over SWD until it wakes; that is why this is canary-first, and why the entry is one function (`enterStopUntilWake` in `lightning_bugs.ino`), waived with `lb-allow-swd-risk` on its three register lines only. No IWDG failsafe is included (a started IWDG resets the chip after at most about 30 s, which would turn sleep into a reset every 30 s, roughly 40 µA more).

> **Verified (no hardware):** the host code, against a simulated device with a temperature-dependent clock (`host/test_lb_sync.py`), the battery policy compiled and driven natively (`tests/test_lb_power_policy.py`), and that the sketch builds and passes the safety checks. **Not verified on a unit:** that `analogRead(ATEMP)`/`analogRead(AVREF)` from the py32duino core return sensible counts on this chip (the raw counts are published in the block, `temp_raw` and `vref_raw`, so check them first), the LED driver's power-up time after `PA15` goes low (`LED_WAKE_LEAD_MS`, 100 ms), and the SWD behaviour of `resync` on a running unit.

## What is this unit running? `info`, firmware versions and the wire format

```sh
python3 host/lb_sync.py info
# Sync block at 0x20000400: firmware 0.4.0 (build a13ccff2+dirty), wire format 4.0
#   compatible with this lb_sync.py (reads it as wire format 4.0); model pulsex
#     clock_sync  ok (v1)
#     temperature ok (v1)
#     ...
#     sync        ok
#     resync      ok
```

Every unit reports three things in the first eight words of its sync block, which never move or change meaning again: the **wire format** (`major.minor`), the **firmware version** (`LB_FW_*` in `firmware/lightning_bugs/lb_version.h`, bumped by hand), and a **build ID** (the first 8 hex digits of the git commit, plus `+dirty` if the tree had uncommitted changes). `tools/lb_flash.py build` stamps the build ID in with a compiler flag and then reads the header back out of the binary, so a build that cannot say what it is fails instead of flashing. A build made some other way (Arduino IDE) reports "build unknown".

`info` works against any format, including ones this script cannot speak, and it recognises the older formats 1-3 (before version reporting) as "wire format N, firmware unknown" rather than "no sync block". `status`, `resync` and `sync` print the same line, every log entry records `fw`, `fw_build`, `fw_dirty` and `format`, and `report` lists the firmware versions in the log and warns when they are mixed.

**Compatibility.** Three independent facts describe a unit, and each answers a different question:

| fact | answers | how it changes |
| --- | --- | --- |
| wire format `major.minor` | which words exist, and where | a minor only *appends* words (the block size word grows); a new major reorders or reinterprets and is unreadable to older scripts |
| firmware version | what the words *mean* | a field recomputed in fw X keeps its name and position, so gate it on firmware, not format |
| model | which hardware it is | the firmware only reports a `model_id` word (`-DLB_MODEL_ID=<id>u`); what each id *can do* lives in Python |

A script reads each unit with **that unit's own layout** (every format ever released is listed in `host/lb_catalog.py`), so an older minor is readable. Whether it is *usable* is decided per command, not globally: `host/lb_catalog.py` maps each command to the **features** it needs (`clock_sync`, `temperature`, `power`, ...), and each feature lists **variants**, newest first, each guarded by a requirement such as `Fields("temp_cdeg") & Firmware(min=(0, 6, 0)) & HasTrait("temp-cal-b")` and carrying the decoder for that case. A command whose *required* features are missing is refused with every reason at once ("`sync` needs clock_sync (v1: wire format 4.0 has no seq)"); a missing *optional* feature (say power on an old unit) is noted and left out of the log record. A newer minor than the script knows is read as its known prefix; a different major, or formats 1-3, is refused with the unit's firmware and format and the script's. `info` prints, per unit, every feature (and which variant it gets) and every command (ok / ok without X / not supported, with reasons).

**Models** are composed in `host/lb_catalog.py` from reusable **traits**: a trait lists the features the hardware can provide and the transports that reach it, so a new board is one line, e.g. `PULSEX.derive(1, "pulsex-lite", drop=("die-temp",))` (no temperature) or `PULSEX.derive(2, "pulsex-radio", add=(Trait("radio", transports=("radio",)),))`. A feature the model has no trait for is reported as unsupported ("model 'pulsex-lite' has no temperature"), and a model is only reachable over the transports its traits list. A board that computes something differently gets a marker trait that a feature variant requires (`HasTrait("temp-cal-b")`), so new boards that share it are picked up without touching the variant. An id the script has never heard of is refused with its number rather than guessed at. Build for a model with `python3 tools/lb_flash.py build --model NAME` (also accepted by `flash`; the default is the first model in `MODELS`, `pulsex`): it sets `-DLB_MODEL_ID` and then reads the id back out of the binary, failing the build if it does not match.

Requirements also cover the *connection* (each `Transport` in the catalog says what it allows): `Access("write")` is what `sync`, `resync` and `hold` need, so a future read-only link can fetch and decode blocks (`Catalog.unit_from_words` identifies a unit from the header, or the whole block, however it arrived) and gets a clear refusal for anything that writes.

To record a change, edit `host/lb_catalog.py` only (its docstring has the recipe): a new minor is a `FormatSpec` plus the struct in `lb_sync.h`; changed semantics are a new, newer `Variant` (keep the old one for old firmware); a new model is a `Model` (id + traits) in `MODELS`, plus a marker trait and variant only where it computes something differently. Format 4.0 has not been flashed to any unit yet, so it may still be amended; after that, only append. Units still running formats 1-3 (if any exist) need reflashing once. The code is in `host/lb_compat.py` (generic, no project data) and `host/lb_catalog.py` (the data).

## Stack budgets

Each model carries `ram_bytes` and `max_stack_bytes` (from its chip trait in `host/lb_catalog.py`; the tightest value among a model's traits wins). `python3 tools/lb_stack.py [--model NAME | --all]` builds the firmware in a scratch directory with `-fstack-usage -fcallgraph-info=su` and computes a worst case: the longest call chain from `main()` (and the static constructors), plus, for each interrupt priority group in `INTERRUPT_GROUPS`, the 32 B exception frame, its longest handler chain and a 32 B allowance for callbacks behind function pointers. Library helpers with no source frame data (divide, memset, startup) are sized from the linked ELF's disassembly. It exits 1 if the total exceeds the model's `max_stack_bytes`, or if that budget is larger than the stack the linker reserves (`_Min_Stack_Size`, 768 B), since the budget would then not be guaranteed. The tests run it for every model (`pytest -m toolchain`; skipped when `arduino-cli` or the core is missing, which includes CI today). It is a static bound over calls the compiler can see, not a measurement of a running unit; if the sketch starts using another interrupt, add it to `INTERRUPT_GROUPS`.

## Build and flash wrapper

First-time setup: in a `claude_sandbox` session nothing needs running by hand. The root `claude_sandbox_deps.yaml` installs `python3-venv` and `libusb` (apt) and runs `tools/setup.sh` at every launch (no root; it installs the pinned `arduino-cli`, the py32duino core and toolchain, and the pyocd venv, and is quick when already done). Then `export PATH="$HOME/.local/bin:$PWD/.venv/bin:$PATH"`. On your own machine the script refuses to run unless you pass `--i-know-this-modifies-my-system`; it then keeps everything under `lightning_bugs/.tools/` (git-ignored) and `.venv`, never touches `~/.local/bin`, `~/.arduino15` or your arduino-cli config, writes only pip's and pyocd's package caches outside the repo, and prints the `PATH` and `ARDUINO_DIRECTORIES_*` exports to use afterwards (Linux only; `lb_flash.py` honours `ARDUINO_DIRECTORIES_DATA`). See `assessments/toolchain.md`.

`tools/lb_flash.py` implements step 3 of `assessments/swd-recovery.md`. Needs `arduino-cli` (with the py32duino core) and `pyocd`.

```sh
python3 tools/lb_flash.py check                          # source safety scan only
python3 tools/lb_flash.py [--fqbn <board>] build         # check + compile + binary check
python3 tools/lb_flash.py options --poll                  # read-only: option bytes (RDP, NRST, watchdog, BOR) and DBGMCU_CR
python3 tools/lb_flash.py watch --timeout 60              # does the chip answer SWD, when, for how long?
python3 tools/lb_flash.py -u <probe> dump                # back up the unit's flash BEFORE flashing it
python3 tools/lb_flash.py -u <probe> flash --canary      # flash a canary unit, verify SWD
python3 tools/lb_flash.py flash --canary --bin build/lightning_bugs.ino.bin --wait   # prebuilt: start it, then wake the unit
python3 tools/lb_flash.py -u <probe> flash               # sealed unit: only canary-tested builds
```

`options` reads the 128-byte option-byte block at `0x1FFF0E80` (read protection, whether NRST is a reset pin, hardware or software watchdogs, brown-out level), the live `FLASH_OPTR` register, and `RCC_APBENR1` to see whether the debug clock (`DBGEN`) is on; only if it is, it also reads the debug block `DBGMCU` at `0x40015800` (`DBGMCU_CR` bit 1 is `DBG_STOP`, the manual's switch for keeping debug clocks alive in stop mode). It writes nothing, and it tells pyocd to skip the Puya pack's `DebugCoreStart` sequence. **That matters:** with it, every ordinary pyocd connection (`dump`, `lb_sync`) sets `DHCSR.C_DEBUGEN` and `DBGEN` and writes `DBGMCU_CR = 2` (`DBG_STOP`) and the freeze registers; the bits stay until a power-on reset (battery disconnect), so a `DBG_STOP = 1` read through an ordinary session says nothing about the original firmware. Use `--poll` (and `--timeout`) on a sleeping unit. Addresses and bit layouts are from the PY32F030 reference manual v1.3 (sections 4.4, 4.8, 8.6.15, 28.9) and the Puya pack `Puya.PY32F0xx_DFP.1.2.8.pdsc`. First reading on the canary (taken with the pack sequence still active): RDP level 0, NRST is a GPIO (no reset pin), IWDG and WWDG are software, BOR off, no write protection.

`watch` is the diagnostic to run first when a connection fails: it keeps the probe open and tries a raw SWD line reset and DP IDR read about 800 times a second (a `--poll` attempt costs about 85 ms, almost all setup), and prints when the chip first answers, its DPIDR (a Cortex-M0+ gives `0x0BB11477`) and how long it kept answering, so you learn whether a connect window exists and how long it is. It reads no flash, halts nothing and exits 1 if the chip never answers.

`flash --wait [SECONDS]` polls until the chip answers SWD (default 120 s) and then runs `pyocd flash` at once, so you start the command first and wake the unit second; pair it with `--bin` after a separate `build` so the compile does not use up the window. The flash itself is run once and never retried: only the poll, which reads one word, repeats. `pyocd flash` halts the core as it connects (its default connect mode), so one connection should hold for the whole flash.

`dump` reads the 64 KB of flash (`0x08000000`) twice over SWD without halting or resetting the chip, and saves it to `backups/dump_<time>_<sha>.bin` (git-ignored; copy it somewhere durable) only if both reads are identical and not all `0x00`/`0xFF` (a read-protected chip can look like that, and such a dump is not a backup). It never overwrites a file. `--output` picks the file and `--size` the length. `--passes 1` takes a single read for a short SWD window (see the wiring notes): it still rejects blank flash but cannot cross-check, so the file is named `*_unverified.bin`; dump again later and compare the sha256 values before trusting it. `--poll` is for a unit that only answers SWD briefly after waking: it retries the connection inside one process (about 8-12 attempts a second, against about 1 s per attempt for a shell loop, which starts Python each time), reads the moment the chip answers, and takes all passes in that one session. It gives up after `--poll-timeout` seconds (default 120). It never halts the core. It does not stop `flash` from running without a backup. (`pyocd read`, which an old comment in `PY32F030EK28.ino` suggests, does not exist in the pinned pyocd.)

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

- **Do not use the three pads labelled SWCLK / GND / SWDIO on the underside of the Pico.** Those are the Pico's *own*
  debug port (for programming the Pico itself) and sit at a steady 3.3 V; the probe firmware never drives them. The
  unit connects to the ordinary pins **GP2 (physical pin 4) and GP3 (physical pin 5)**, and GND to any GND pin (3, 8, ...).
- GP2 = SWCLK and GP3 = SWDIO are the Pico debug-probe firmware's default pins (`debugprobe` v2.3.1,
  `include/board_pico_config.h`). GP1 is its target-reset (nRESET) output, unused here.
- The series resistors are there because the Pico drives 3.3 V while the unit runs at battery voltage (up to ~4.2 V,
  ~5 V on USB).
- Power the unit from its own battery. Do not connect the Pico's VBUS/VSYS to the unit, and do not plug a charger
  or USB host into the breakout while the probe is wired to A5/B5 (their CC lines would drive the SWD pins).
- **The unit sleeps, and SWD is unavailable while it does** (hijack README: normally in deep sleep or stop; the slide
  switch wakes it and opens a "small connect window", and plugging in a charger opens another). Run the probe command
  with `dump --poll` (or `--poll --passes 1`), then move the switch, so an attempt lands in the window. `dump` reads the flash twice by default, which needs
  the link to stay up the whole time (`--passes 1` needs half as long); a very slow `--frequency` stretches that, so do not go lower than needed.
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
