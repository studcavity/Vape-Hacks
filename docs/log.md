## 2026-11-19

- Compared the canary's original firmware with the upstream `backup_flash.bin`: a smaller build (about 2.3 KB less code) with the same stack pointer and reset vector; details in `tooling/unit-orange-fab.md`.
- Read Peach Jam's DPIDR and UID: DPIDR `0x0BC11477`, same as the canary; changed `lb_flash.py`'s expected value to match.
- Flashed firmware 0.5.1 to the canary; recorded what the switch-off sleep shows so far (logic works, STOP itself not yet verified) in `tooling/unit-orange-fab.md` and `lightning-bugs/power-policy.md`.
- Flashed the diagnostic build to the canary and recorded the switch readings in `hardware/mode-switch.md`: GND, middle and VDDA bands, PA3 inert, and two spurious PA2 edges per analog read at VDDA (fixed in firmware 0.5.1).
- Recorded the canary's option bytes in `tooling/unit-orange-fab.md` (same as Peach Jam's; `DBG_STOP` set by the earlier pyocd connections).
- Added `tooling/unit-peach-jam.md` (the first unit; hash and option bytes from the 2026-11-17 checkpoint, DPIDR not recorded). Orange fucking fab is the canary; its dump hash is recorded, and it differs from the upstream `backup_flash.bin` in 27,697 bytes.
- Added `tooling/unit-orange-fab.md`: the unit's SWD connect windows and DPIDR from `watch`; recorded that `dump` does not gate on the chip ID.
- Shelved the automatic low-battery sleep; the firmware now sleeps only when the slide switch is at its off pole. `lightning-bugs/power-policy.md` keeps the shelved design and its constants.
- Converted the lasting parts of `toolchain.md`, `swd-recovery.md` and `py32c642-prior-art.md` into `tooling/` and `references/`; linked the migrated code-review bundle from `lightning-bugs/`. The 2026-11-17 checkpoint was only mined for the canary's option bytes.
- `references/pdf-sources.md`: noted that `poppler-utils` is pre-installed once the deps-file change merges.
- Created the bundle: hardware, display, firmware, lightning-bugs, tooling and references.
- Recorded the first PDF findings (UID, factory config, Vrefint range) in `references/`.
