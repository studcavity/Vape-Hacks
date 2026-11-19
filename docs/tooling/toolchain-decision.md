---
type: Decision
title: "Toolchain: arduino-cli installed by setup.sh"
description: "Why we build with a pinned arduino-cli and the py32duino core instead of PlatformIO or a distro package, and what could break it."
tags: [tooling, toolchain, arduino-cli, decision]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:20:00Z" }
sources:
  - id: assessment
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/toolchain.md
    title: Toolchain assessment (original, kept as history)
  - id: setup
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/tools/setup.sh
    title: setup.sh
---

**Decision:** keep `arduino-cli`, installed by `lightning_bugs/tools/setup.sh` as a pinned, checksum-verified binary.
No distro packages and no root.[^assessment]

**Why not the alternatives** (checked on 2026-11-17 to 2026-11-19):[^assessment]

- **PlatformIO has no PY32 support.** PlatformIO Core 6.2.0 found only an unrelated PY32F002A library; the py32duino core has no PlatformIO files.
- **`arduino-cli` is easy to get without the distro.** It is one static Go binary on GitHub releases. Upstream's `install.sh` was rejected because it never verifies the tarball.
- **Porting alternatives exist but cost real work:** PlatformIO's GCC package plus a custom platform script, or a Makefile/CMake with the packaged `arm-none-eabi-gcc` (fewest moving parts, not done).

**What gets installed.** `arduino-cli` 0.33.0 (the version the core's own CI uses), the `PY32Duino:PY32@0.1.3` core from a package index, the xpack `arm-none-eabi-gcc` it pulls in (about 256 MiB), CMSIS 5.7.0, and a venv with `pyocd` plus the Puya pack. The build uses FQBN `PY32Duino:PY32:GenF030:pnum=PY32F030x8`.[^assessment]

**Caveats**

- The core index URL is a CI "Nightly" release asset, not a stable endpoint. If it vanishes, install the core from the `Arduino-PY32-0.1.3.zip` release by hand, with the toolchain and CMSIS.
- The `pyocd pack install py32f030x8` step is unversioned, so it is a moving input (see [tooling risks](../../lightning_bugs/assessments/2026-11-19-code-review/risks-tooling.md)).
- In a sandbox everything installs outside the repo except `lightning_bugs/.venv`. On your own machine, `setup.sh --i-know-this-modifies-my-system` keeps it all under `lightning_bugs/.tools/`.
- A harmless warning appears at build: "library SrcWrapper claims to run on AirMCU architecture(s)".
- Build size when last checked: 13,308 bytes of 65,536 flash, 1,360 of 8,192 RAM. Nothing has been flashed or run on a device.

**Staleness.** Version pins and the build numbers above are from 2026-11-19; re-check them after any bump of `setup.sh`.

[^assessment]: Toolchain assessment (original, kept as history)
