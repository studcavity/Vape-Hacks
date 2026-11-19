# Log

## 2026-11-19

* **Migrate** - bundle moved to OKF v0.3 (quoted timestamps, source URLs, root title and description). The four fixed defects are now `deprecated`; the three open ones were re-read against the code and stay current; the overview's next steps were updated.
* **Fix** - [post-flash result check](defect-flash-no-result-check.md): the running build must match the flashed `.bin`; `--bin` is checked against the checked-out commit.
* **Fix** - [auto_unlock](defect-flash-auto-unlock.md): `pyocd flash` and `pyocd reset` now get `-O auto_unlock=false`.
* **Fix** - [lit LEDs after a mid-show resync](defect-led-lit-after-resync.md): the driver is blanked and unpowered before waiting; native sketch test added.
* **Fix** - [resync fallback grid](defect-resync-fallback-grid.md): `resync` now refuses to guess the grid on a just-booted unit.
* **Create** - first review of the whole project; seven defects and two risk lists recorded.
