# Lightning Bugs

* [Lightning Bugs low-battery policy](power-policy.md) - When the firmware stops showing and sleeps to protect the unprotected cell: thresholds, confirmation, wake window and USB handling.
* [Lightning Bugs sync design](sync-design.md) - How devices share a time base over SWD: the RAM sync block, anchor, rate correction and beat grid, and what accuracy to expect.
* [Hourly resync, visit log and report](hourly-resync-and-log.md) - The routine visit workflow: first sync, `resync` each time you plug in, the JSONL log, temperature capture and `report`.
* [Sync block wire format and compatibility](wire-format-and-compat.md) - How a unit reports its wire format, firmware version and model, and how the host reads any version through lb_catalog.py.

Older assessments of the same project, not yet converted, are in [`lightning_bugs/assessments/`](../../lightning_bugs/assessments/).
