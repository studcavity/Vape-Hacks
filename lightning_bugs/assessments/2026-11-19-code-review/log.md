# Log

## 2026-11-19

* **Fix** - [auto_unlock](defect-flash-auto-unlock.md): `pyocd flash` and `pyocd reset` now get `-O auto_unlock=false`.
* **Fix** - [lit LEDs after a mid-show resync](defect-led-lit-after-resync.md): the driver is blanked and unpowered before waiting; native sketch test added.
* **Fix** - [resync fallback grid](defect-resync-fallback-grid.md): `resync` now refuses to guess the grid on a just-booted unit.
* **Create** - first review of the whole project; seven defects and two risk lists recorded.
