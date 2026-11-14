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

## Proposed plan

1. Add a RAM "sync block" to the firmware: epoch, period (µs), rate correction (ppm).
2. Write a host-side pyocd script that measures offset and drift, then writes the sync block.
3. Rework the animation loop to run on scheduled beats instead of `delay()`.
4. Later, if devices must stay locked unplugged for long sessions, add a pulse input (IR or wired) handled by timer input capture.
