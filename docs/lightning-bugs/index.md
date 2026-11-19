# Lightning Bugs

* [Lightning Bugs sleep and battery policy](power-policy.md) - The firmware sleeps only when the slide switch is at its off pole and has no automatic low-battery protection; the shelved design is kept here.
* [Lightning Bugs sync design](sync-design.md) - How devices share a time base over SWD: the RAM sync block, anchor, rate correction and beat grid, and what accuracy to expect.
* [Hourly resync, visit log and report](hourly-resync-and-log.md) - The routine visit workflow: first sync, `resync` each time you plug in, the JSONL log, temperature capture and `report`.
* [Sync block wire format and compatibility](wire-format-and-compat.md) - How a unit reports its wire format, firmware version and model, and how the host reads any version through lb_catalog.py.

## Review
* [Code review, 2026-11-19](../../lightning_bugs/assessments/2026-11-19-code-review/index.md) - Its own OKF bundle: four defects fixed, three open, plus hardware and tooling risks.

The original assessments (`toolchain.md`, `swd-recovery.md`, `py32c642-prior-art.md`, the 2026-11-17 session checkpoint) stay in
[`lightning_bugs/assessments/`](../../lightning_bugs/assessments/) as dated history; code comments refer to them. Their lasting content
is in [tooling](../tooling/index.md) and [references](../references/index.md).
