---
type: Procedure
title: "Running the tests"
description: "How to run the hardware-free test suites and linters, what each layer covers, and what is not covered."
tags: [tooling, tests, ci]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/README.md
    title: Repository README (Running the tests)
  - id: claude-md
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/CLAUDE.md
    title: Repository CLAUDE.md
---

Nothing here needs hardware, `pyocd` or `arduino-cli`; device and toolchain are simulated or faked.[^readme]

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                    # everything, about 1 s
.venv/bin/python -m pyflakes $(git ls-files '*.py') && shellcheck lightning_bugs/tools/setup.sh
```

| Layer | Path |
|---|---|
| Unit: `lb_flash.py` safety rules, `lb_sync.py` helpers | `lightning_bugs/tests/` |
| Simulated-device clock sync | `lightning_bugs/host/test_lb_sync.py` |
| Repo hygiene: `.gitignore`, deps and host yaml, `setup.sh` guard | `tests/` |
| `lb_flash.py` end to end with fake tools | `lightning_bugs/tests/test_lb_flash_integration.py` |

CI (`.github/workflows/ci.yml`) runs lint, the unit tests on Python 3.10, 3.12, 3.14, the repo checks and the integration tests on every push.[^readme]
Flashing a real unit is still manual and canary-first.[^claude-md]

[^readme]: Repository README (Running the tests)
[^claude-md]: Repository CLAUDE.md
