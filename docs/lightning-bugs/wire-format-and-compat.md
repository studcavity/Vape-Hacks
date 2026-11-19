---
type: Design
title: "Sync block wire format and compatibility"
description: "How a unit reports its wire format, firmware version and model, and how the host reads any version through lb_catalog.py."
tags: [lightning-bugs, wire-format, compatibility]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-19T03:30:00Z" }
sources:
  - id: lb-readme
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/README.md
    title: Lightning Bugs README
  - id: catalog
    resource: https://github.com/studcavity/Vape-Hacks/blob/main/lightning_bugs/host/lb_catalog.py
    title: lb_catalog.py (formats, variants, traits, models)
---

`python3 host/lb_sync.py info` tells you what a unit runs. The first eight words of the sync block (at
`0x20000400` in the README's example) never move or change meaning, and carry three independent facts:[^lb-readme]

| Fact | Answers | How it changes |
|---|---|---|
| wire format `major.minor` | which words exist, where | a minor only appends words; a new major reorders or reinterprets |
| firmware version (`LB_FW_*`) | what the words mean | a field recomputed in a new firmware keeps its name and position, so gate on firmware, not format |
| model (`LB_MODEL_ID`) | which hardware | firmware reports an id; what it can do lives in Python |

The host reads each unit with that unit's own layout; every format ever released is listed in `host/lb_catalog.py`,
and models are composed from reusable *traits* of features and transports. Each command states its requirements
(for example `Access("write")` for `sync`, `resync` and `hold`), so an older unit can still be inspected even when a command is unavailable.[^lb-readme][^catalog]

To record a change, edit `lb_catalog.py` only (its docstring has the recipe): a new minor is a `FormatSpec` plus
the struct in `lb_sync.h`; changed semantics are a new, newer `Variant`.[^lb-readme] Formats 1 to 3 predate
version reporting and show up as "wire format N, firmware unknown". Stack and RAM budgets per model come from the
same catalog (`tools/lb_stack.py`).[^lb-readme]

[^lb-readme]: Lightning Bugs README
[^catalog]: lb_catalog.py (formats, variants, traits, models)
