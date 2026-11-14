# Keeping SWD reachable: assessment and plan

**Goal:** reflash Lightning Bugs devices as many times as we want, without opening them.

**Problem:** recovering through the boot guard (`lbBootGuard()`) needs a reset. The slide switch doesn't cut power to the MCU, so a reset currently means disconnecting the battery, which means taking the device apart.

> **Unverified details:** the register names here (GPIO mode/alternate-function registers, DBGMCU debug and freeze bits, IWDG, option bytes, NRST mode) come from general PY32F0/STM32F0 family knowledge. They have **not** been checked against `PY32F030 Reference manual v1.3_EN.pdf`. Verify each one before implementing.

## What can actually lose SWD

Most bugs can't. Crashes, hard faults, infinite loops and disabled interrupts leave SWD working, because the debug hardware runs independently of the CPU. SWD is only lost when firmware does one of these:

1. **Reconfigures PA13/PA14**, e.g. `pinMode(PA13, …)` or a raw write to the GPIOA mode registers.
2. **Enters a deep low-power mode** (STOP/STANDBY) without the debug-in-low-power bits set.
3. **Stops or drastically slows the system clock.** The debugger reads memory over the system bus, which needs that clock.
4. **Changes option bytes or flash protection**: read protection, write protection, or the NRST pin mode. This is the only category that might be truly permanent.
5. **Damages the pins electrically.**

The plan is to make 1–4 hard to do by accident, and to provide a way to reset the chip without opening it.

## On-device firmware mitigations

- **Never use PA13/PA14.** Lightning Bugs doesn't need them, so this is an absolute rule, not something to manage.
- **Self-healing SWD check.** A small `lbSwdGuard()` runs from the main loop and from `lbWaitUntil()`. It puts PA13/PA14 back in SWD mode if anything changed them, turns off deep sleep (`SCB->SCR` SLEEPDEEP), and sets the DBGMCU bits that keep debug working in low-power modes.
- **Independent watchdog (IWDG) as a safety net.** Start it right after the boot guard and reset it only from inside `lbSwdGuard()`. It runs on its own oscillator (LSI) and can't be stopped once started. So a hang, a stuck low-power mode or a dead system clock becomes a reset, which puts the chip back in the boot guard where `lb_sync.py hold --wait` can catch it.
  - It must be set to pause while the core is halted (DBGMCU freeze bit), or flashing and debugging would trigger resets.
  - Never enable it through option bytes ("hardware watchdog" mode).
- **Hold the button to force a reset.** The watchdog-reset function only resets the watchdog while the button (PB1) is up. Holding the button for about 8 seconds resets the chip into the guard, even if the app's own button handling is broken. This holds as long as the watchdog is reset only from that one place in `lb_sync.h`. Normal button holds are under 2 seconds.
- **Flash writes** (e.g. if we later store the rate correction): one dedicated page with checked bounds. Option bytes are never touched.
- **Optional, more effort:** split the guard and watchdog setup into a tiny first-stage loader in the first flash page, and flash the app only after it. Then app updates can't break the guard itself.

## Hardware, done once while the device is open

- **Bring NRST out to an unused USB-C pin.** This is the best single fix, if it works on this board. With NRST the debugger can "connect under reset" and take control before any firmware runs, which recovers from everything except option-byte damage. Check first:
  - **Is NRST still a reset pin?** Option bytes can turn it into a GPIO, and the original firmware may have done that. Read the option register with pyocd before soldering.
  - **Which USB-C pins are free?** SBU (A8/B8) or D+/D− may be unconnected, since this chip has no USB peripheral. Check continuity.
- **A power cut that doesn't need disassembly**, e.g. a reed switch in the battery lead that a magnet can open. The boot guard already makes a power-cycle enough to recover.
- **Protecting the pins:** keep the series resistors on the probe lines. Because the USB-C configuration resistors (on A5/B5, the CC pins) were removed, a USB-C charger now pulls the SWD pins up toward 5 V. The current is microamps, so the risk is low, but it's another reason to charge with a USB-A cable.
- **Last resort with no disassembly:** let the battery run flat. When it's recharged, the chip boots fresh, so the guard can be caught with `hold --wait`. Slow, but it works.

## Guards in the code and process

- **Safety check script** that blocks the build if:
  - the source mentions PA13/PA14, raw GPIOA mode/alternate-function writes, STOP/STANDBY, deep-sleep bits, option-byte keys or functions, or switching the system clock to LSI/LSE. A deliberate exception needs an explicit allow comment.
  - the compiled firmware contains HAL option-byte or STOP/STANDBY functions (checked with `arm-none-eabi-nm`, which the Arduino toolchain installs), or the option-byte unlock key values appear in the `.bin`.
- **Flash wrapper** that refuses to flash if the check fails. After flashing, it resets the chip and confirms it can reconnect three times: during the guard, after the guard, and 30 seconds later.
- **Canary unit:** one device kept open, with the battery reachable or NRST wired. The wrapper identifies each chip by its unique ID and refuses to flash a sealed device with any build that hasn't passed on the canary first.
- **Rules in `CLAUDE.md` for coding agents:** the never-do list above; always run the check script; never write option bytes or flash registers by hand; never flash a sealed device without the user's confirmation.

## Proposed plan

1. **Canary unit, plus NRST wired to USB-C if the checks pass.** No firmware changes, and covers almost everything. First step: a pyocd command to read the option bytes and confirm NRST is still a reset pin.
2. **Firmware:** self-healing `lbSwdGuard()`, watchdog, and button-forced reset in `lb_sync.h`.
3. **Process:** safety check script, flash wrapper with canary enforcement, and `CLAUDE.md` rules.

## Status

- [ ] Verify register details against the reference manual
- [ ] Read option bytes; confirm NRST mode
- [ ] Check USB-C pins for an unused line to carry NRST
- [ ] Set up a canary unit
- [ ] Implement firmware mitigations (step 2)
- [ ] Implement check script, flash wrapper, `CLAUDE.md` rules (step 3)
