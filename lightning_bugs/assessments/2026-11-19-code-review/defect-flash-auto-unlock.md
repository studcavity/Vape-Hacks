---
type: Defect
title: The flash command does not disable pyocd auto_unlock
description: lb_flash.py claims the flash step never mass-erases, but the pyocd flash command keeps the default auto_unlock=True.
tags: [tooling,safety]
status: draft
confidence: read from code; pyocd defaults checked in the installed 0.46.1
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../tools/lb_flash.py
  - resource: ../../host/lb_sync.py
---

# Problem

`lb_sync.open_session` sets `connect_mode=attach` and `auto_unlock=False`. `lb_flash.cmd_flash` runs `pyocd flash` and `pyocd reset` as subprocesses with neither option, so pyocd's default `auto_unlock=True` applies. The module docstring says "the flash step never mass-erases".

# Failure

Probably none with the Puya pack, since the generic CMSIS-pack target has no unlock handling, but nothing enforces it. pyocd's default erase mode for `load` and `flash` is sector, not chip.

# Fix

Pass `-O auto_unlock=false` to both subprocess calls, and test that it is present.

# Resolution

Fixed on branch `sbx/jolly-shannon/02-review-doc-and-fixes`: `lb_flash.py` passes `-O auto_unlock=false` (`NO_UNLOCK`) to both the `pyocd flash` and `pyocd reset` subprocesses. Test: `test_pyocd_subprocesses_are_told_not_to_auto_unlock` parses the recorded arguments with pyocd's own option parser and fails without the change. `pyocd flash` still halts the core on connect (its default connect mode); only unlocking is disabled.
