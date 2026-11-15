# Instructions for coding agents

## Pull requests: sandbox fork only

This repository (`studcavity/Vape-Hacks`) is a sandbox fork of the original project at `SwiggityCricket/Vape-Hacks`.

- **Never open a pull request, issue, or comment against `SwiggityCricket/Vape-Hacks`** (the upstream/original repository). This applies to all work, including the `lightning_bugs` project.
- PRs may only target `studcavity/Vape-Hacks`. With `gh`, always pass `--repo studcavity/Vape-Hacks` explicitly; `gh pr create` on a fork can otherwise default to the upstream parent.
- Never push to, or add as a push remote, any upstream repository.

## Compiled binaries: don't commit them by default

Build outputs (`.elf`, `.hex`, `.map`, `.bin`, `.o`, `build/`) are generated and are not tracked (`*.bin` is git-ignored). Do not `git add` them.

Only commit a compiled binary if one of these is true:

- The user has explicitly told you to.
- It is the **only copy of code that cannot be regenerated**, such as a flash dump read from a device whose source we don't have (e.g. `backup_flash.bin`). Even then, **ask the user before committing it**.

If a build produces binaries inside the tree, add them to `.gitignore` instead of committing them.

## Probe parity (two supported stacks)

The Lightning Bugs host tools support **two debug-probe stacks, and both are considered supported for now**:

- **Stack A, Raspberry Pi Pico** running debug-probe (CMSIS-DAP) firmware, via pyocd's built-in drivers
  (USB `2e8a:000c`).
- **Stack B, FTDI FT232R** USB-UART adaptor, via the plugin in `lightning_bugs/probes/ft232r/`
  (USB `0403:6001`; select with `--probe ft232r:`).

**Always implement changes for both to keep parity.** That covers `lb_flash.py` / `lb_sync.py`, `setup.sh`,
`claude_sandbox_deps.yaml` and any USB passthrough or sandbox configuration, tests, CI and docs. If you
change something for one stack, either do the same for the other in the same change or say explicitly why
it cannot be done and record the gap in `lightning_bugs/probes/ft232r/README.md`. Keep `lb_flash.py` and
`lb_sync.py` probe-agnostic (they talk only to pyocd; the probe is chosen with `--probe`); put probe-specific
code in the probe's own package. `tests/test_probe_parity.py` guards some of this. `pyocd` and `pyftdi` are pinned exactly in `lightning_bugs/constraints.txt` (used by `setup.sh` and
`requirements-dev.txt`); bump them there, once, and run the whole suite. Remove this section only
when the user says one stack is retired.

## Tests

Tests live in the repo and run in CI (`.github/workflows/ci.yml`). Use a venv:

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest                 # everything
    .venv/bin/python -m pyflakes $(git ls-files '*.py') && shellcheck lightning_bugs/tools/setup.sh

- `lightning_bugs/host/test_lb_sync.py`: simulated-device sync tests (no hardware).
- `lightning_bugs/tests/`: unit tests for `lb_flash.py` safety rules and `lb_sync.py` helpers.
- `lightning_bugs/tests/test_lb_flash_integration.py`: drives `lb_flash.py` against fake `arduino-cli`/`pyocd`.
- `lightning_bugs/tests/ft232r/`: the FT232R plugin against a pin-level simulated SW-DP (wire, transport, SWD, probe, pyocd `DebugPort`, `lb_sync`).
- `tests/`: repo hygiene (`.gitignore`, `claude_sandbox_deps.yaml`, `setup.sh` guard).
- Nothing here touches real hardware; flashing a device is still a manual, canary-first step.
