# Vape-Hacks
Hacking stupid "disposable" vapes to do fun things and not be e-waste.

## Running the tests

The tests need no hardware, no `pyocd` and no `arduino-cli`: device and toolchain are simulated or faked.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # pytest, pyyaml, pyflakes
.venv/bin/python -m pytest                        # everything (~1 s)
```

Run one layer, from smallest to largest:

| What | Command |
|---|---|
| Unit: `lb_flash.py` safety rules, `lb_sync.py` helpers | `.venv/bin/python -m pytest lightning_bugs/tests/test_lb_flash_unit.py lightning_bugs/tests/test_lb_sync_helpers.py` |
| Simulated-device clock sync | `.venv/bin/python -m pytest lightning_bugs/host` |
| Repo hygiene: `.gitignore`, `claude_sandbox_deps.yaml`, `setup.sh` guard | `.venv/bin/python -m pytest tests` |
| `lb_flash.py` end to end with fake `arduino-cli`/`pyocd` | `.venv/bin/python -m pytest lightning_bugs/tests/test_lb_flash_integration.py` |

Skip the tests that drive real `git`/`bash` processes with `-m "not integration"`.

Lint, as CI does (`shellcheck` comes from your package manager, e.g. `apt install shellcheck`):

```sh
.venv/bin/python -m pyflakes $(git ls-files '*.py')
shellcheck lightning_bugs/tools/setup.sh
```

Lint takes the file list from `git ls-files` because `setup.sh` creates `lightning_bugs/.venv`, which pyflakes would otherwise scan.

CI (`.github/workflows/ci.yml`) runs everything on Ubuntu 24.04 and 26.04 runners: lint, the unit tests on Python 3.10, 3.12 and 3.14 (3.14 only on 26.04, 3.10 only on 24.04), the repo checks, and the integration tests, on every push.

Not covered: anything that needs a real probe or device. Flashing is still a manual step and must go through a canary unit first (see `lightning_bugs/README.md`). A few `setup.sh` tests depend on whether `/etc/claude-sandbox` exists and run only on the matching side: inside a sandbox the sandbox-mode run is exercised, elsewhere (CI, your machine) the refusal and the `--i-know-this-modifies-my-system` mode are. All of them use fake `arduino-cli`/`python3`, so nothing is downloaded or installed.
