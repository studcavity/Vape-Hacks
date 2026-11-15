# Toolchain assessment: building without distro packages

**Question:** `arduino-cli` isn't in the maintainer's distro repos and Arduino's dependency stack is a pain. Is there an alternative, in particular PlatformIO (VS Code + `pio` CLI) or the tools it uses directly?

**Decision:** keep `arduino-cli`, installed as a pinned, checksum-verified binary by `tools/setup.sh`. No distro packages, no root. Alternatives are documented below in case this stops being good enough.

## What was checked

| Question | Finding |
|---|---|
| Does PlatformIO support PY32? | **No.** Installed PlatformIO Core 6.2.0 in a scratch venv; `pio pkg search py32` returns only a PY32F002A low-power library and an unrelated I2C library. No platform, no board. |
| Does the py32duino core support PlatformIO? | **No.** `py32duino/Arduino-PY32` has no PlatformIO files. It is a plain Arduino core (`boards.txt`, `platform.txt`, `cores/arduino`, `variants/PY32F030xx`). |
| Is `arduino-cli` hard to get without the distro? | **No.** It is one static Go binary on GitHub releases. The core's own CI installs it and the core this way. |
| Where does the core come from? | An Arduino package index: `https://github.com/PY32Duino/Arduino-pack-json-ci/releases/download/Nightly/package_py32_index.json` (taken from the core's `.github/workflows/test.yml`). |
| What does the core pull in? | `PY32Duino:PY32@0.1.3`, an xpack `arm-none-eabi-gcc` (13.2.1-1.1 resolved by the index, ~256 MiB), CMSIS 5.7.0, AirISP. All fetched by `arduino-cli core install`, nothing from the distro. |

## What was done

`tools/setup.sh` (re-runnable):

1. Downloads `arduino-cli` 0.33.0 (the version the core's CI uses) from GitHub releases, verifies it against the release checksum file, installs to `~/.local/bin`. Not a `curl | sh`.
2. Installs `PY32Duino:PY32@0.1.3` through that index.
3. Creates `lightning_bugs/.venv` with `pyocd` and installs the Puya pack (`Puya.PY32F0xx_DFP`); target `py32f030x8` is then known to pyocd.

Then `tools/lb_flash.py build` compiles with FQBN `PY32Duino:PY32:GenF030:pnum=PY32F030x8`.

## Verified on this machine

- Core and toolchain install cleanly; `arduino-cli core list` shows `PY32Duino:PY32 0.1.3`.
- The Lightning Bugs sketch **compiles**: 13,308 bytes of 65,536 flash (20%), 1,360 bytes of 8,192 RAM (16%).
- `uwTick` is linked (the sync tool's counter) and `SysTick_Handler` / `HAL_InitTick` are present. `HAL_PWR_Enter*` and option-byte functions are not linked.
- `lb_flash.py` source and binary checks pass; the canary gate correctly refuses a sealed flash.
- Host tests pass. Nothing has been flashed or run on a device.

**Correction found while building:** the first binary check failed on `HAL_RCC_OscConfig`. It is linked by the core's own boot-time `SystemClock_Config()` in every sketch (the stock firmware too), so it can't be a rule. It was removed from the binary check; the source check still forbids our code from touching RCC or defining `SystemClock_Config`.

**Harmless warning:** `library SrcWrapper claims to run on AirMCU architecture(s)`. Ignore it.

## Alternatives, if arduino-cli stops being acceptable

1. **PlatformIO as a toolchain provider.** `pio pkg install -g -t platformio/toolchain-gccarmnoneeabi` gives a GCC, but you would still need a custom platform/`platformio_build.py` to compile the core's `cores/arduino`, `system/` HAL and `variants/PY32F030xx`. Real porting work, unmaintained by anyone else.
2. **Plain Makefile/CMake with `arm-none-eabi-gcc`** (packaged by Debian/Ubuntu). Same porting work (include paths, defines, linker script from `platform.txt` and `boards.txt`), but fewest moving parts. Not done.

## Caveats

- Index URL is a CI "Nightly" release asset, not a stable endpoint. If it disappears, install the core from the release zip (`Arduino-PY32-0.1.3.zip`) into `~/.arduino15/packages/PY32Duino/hardware/PY32/0.1.3/`, and the xpack toolchain and CMSIS 5.7.0 by hand.
- The 0.33.0 pin is old; newer arduino-cli should work but is untested here.
- Everything installed lives outside the repo (`~/.local/bin`, `~/.arduino15`, `lightning_bugs/.venv` which is git-ignored). A fresh sandbox needs `tools/setup.sh` again (~260 MiB download).
