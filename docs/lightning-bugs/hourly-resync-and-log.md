---
type: Procedure
title: "Hourly resync, visit log and report"
description: "The routine visit workflow: first sync, `resync` each time you plug in, the JSONL log, temperature capture and `report`."
tags: [lightning-bugs, resync, log, temperature]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
---

The firmware plays one show, the stock firmware's halo "comet chase" of about 6 s, at the start of each beat and
keeps the panels dark otherwise.[^lb-readme]

```sh
python3 host/lb_sync.py sync   --every 3600 --epoch 0     # once per unit (about 10 min)
python3 host/lb_sync.py resync                            # each visit, about 15 s
python3 host/lb_sync.py report                            # drift statistics so far
```

- `resync` uses the anchor already in the unit's RAM from the previous visit as the baseline, so an hour apart gives about 0.5 ppm rate resolution.[^lb-readme]
- **Device ID.** The firmware copies the factory UID (16 bytes at `0x1FFF0E00`) into the sync block so each visit is tied to a physical chip; layout in [memory map and information pages](../references/rm-memory-map-and-info-pages.md).
- **Temperature.** Die temperature is read every 10 s while idle (never within 0.3 s of a show frame), converted with `TS_CAL1`/`TS_CAL2` and scaled by the supply seen through Vrefint; limits in [Temperature sensor](../references/ds-temperature-sensor.md). The block keeps latest, min, max and mean since the last sync.
- **Log.** `logs/lb_sync_log.jsonl` (git-ignored; `--log` moves it, `--no-log` skips) gets a line per `sync` and `resync`: UID, `drift_ms` (positive means device ahead), `raw_rate_ppm`, temperature stats, supply voltage, correction written. Copy it somewhere durable.
- `report` needs no hardware: per device it prints the rate mean and spread, temperature range, a ppm/°C fit (three or more visits) and residual drift per hour.

A unit that has slept (low battery) needs a full `sync`; see [power policy](power-policy.md).

[^lb-readme]: Lightning Bugs README
