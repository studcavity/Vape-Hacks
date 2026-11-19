# Tooling

* [Build and flash with lb_flash.py](build-and-flash.md) - The arduino-cli and pyocd wrapper: safety scan, canary-first flashing, backup dump, option-byte and SWD diagnostics.
* [Toolchain: arduino-cli installed by setup.sh](toolchain-decision.md) - Why we build with a pinned arduino-cli and the py32duino core instead of PlatformIO or a distro package, and what could break it.
* [What can make a unit unreachable over SWD](swd-loss-threats.md) - The five ways firmware or hardware can lose SWD access, and what the canary unit's option bytes showed.
* [SWD recovery plan and what is built](swd-recovery-plan.md) - Planned mitigations for losing SWD (watchdog, self-healing check, forced reset, canary process) with which parts exist today.
* [Running the tests](testing.md) - How to run the hardware-free test suites and linters, what each layer covers, and what is not covered.
* [Wiring a Pico debug probe to the unit over USB-C](swd-wiring.md) - How SWD reaches the MCU through the USB-C CC pins, the Pico wiring, resistors, and why the unit is unreachable while asleep.
