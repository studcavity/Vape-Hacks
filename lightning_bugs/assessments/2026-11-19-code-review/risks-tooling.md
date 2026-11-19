---
type: Risk
title: Tooling and supply-chain risks
description: Unpinned inputs to setup.sh, a heuristic safety scan, self-declared canaries and other tooling weaknesses.
tags: [tooling,supply-chain]
status: draft
confidence: read from code
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../tools/setup.sh
  - resource: ../../tools/lb_flash.py
  - resource: ../../host/lb_sync.py
---

# Moving inputs

- `setup.sh` installs `PY32Duino:PY32@0.1.3` from a GitHub "Nightly" index URL. The version is pinned, but the index it comes from changes.
- `setup.sh` runs `pyocd pack install py32f030x8` with no version. That pack supplies the flash algorithm and the register-writing debug sequence.

# Heuristic guards

- The source safety scan is regex-based. It misses `GPIO_PIN_13`, HAL or LL calls and macro tricks. It scans only the sketch directory, and a `//` inside a string literal truncates that line.
- `--canary` is self-declared. The plan said chips would be identified by UID; they are not, so `--canary` on a sealed unit works if mistyped.

# Smaller items

- `build_stamp` runs `git status` over the whole repo, so a change anywhere marks the firmware "+dirty".
- `run_with_target` in `lb_sync.py` retries on any exception, so a log-file write failure after a successful sync is reported as "SWD connection failed".
- The README Status checklist and its "initial feasibility" framing are stale.
