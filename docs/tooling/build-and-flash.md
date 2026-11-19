---
type: Procedure
title: "Build and flash with lb_flash.py"
description: "The arduino-cli and pyocd wrapper: safety scan, canary-first flashing, backup dump, option-byte and SWD diagnostics."
tags: [tooling, build, flash, safety]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README (Build and flash wrapper section)
  - id: toolchain
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/assessments/toolchain.md
    title: Toolchain assessment
---

`tools/lb_flash.py` wraps `arduino-cli` (with the py32duino core) and `pyocd`.[^lb-readme] `tools/setup.sh` installs a
pinned, checksum-verified `arduino-cli` and the core without distro packages (PlatformIO has no PY32 support).[^toolchain]

| Command | Purpose |
|---|---|
| `check` | source safety scan only |
| `build` | check, compile, then binary check |
| `options --poll` | read-only: option bytes (RDP, NRST, watchdog, BOR) and `DBGMCU_CR` |
| `watch --timeout 60` | does the chip answer SWD, when, and for how long |
| `dump` | read the 64 KB flash twice, save to `backups/` only if both reads match and are not blank |
| `flash --canary` | flash the open canary unit and verify SWD |
| `flash` | sealed unit: only builds already passed on the canary |

**Safety rules.** The build is refused if the sketch touches PA13/PA14, raw GPIOA mode writes, STOP/STANDBY,
deep-sleep bits, flash or option-byte access, RCC clock changes or DBGMCU (waive a line with
`// lb-allow-swd-risk`); the ELF and `.bin` are then checked for forbidden HAL symbols and flash-unlock keys.
After flashing it resets the chip and re-attaches three times (in the guard, after it, 30 s later), and compares the
unit's reported firmware version, wire format and build ID with the flashed `.bin`.[^lb-readme]

Rationale and the loss-of-SWD threat list: [what can lose SWD](swd-loss-threats.md) and the [recovery plan](swd-recovery-plan.md). The
register facts that assessment calls unverified (option bytes, debug-in-low-power bits) are not yet checked against
the reference manual; findings so far are listed in [reading the PDFs](../references/pdf-sources.md). Wiring: [SWD wiring](swd-wiring.md).

[^lb-readme]: Lightning Bugs README (Build and flash wrapper section)
[^toolchain]: Toolchain assessment
