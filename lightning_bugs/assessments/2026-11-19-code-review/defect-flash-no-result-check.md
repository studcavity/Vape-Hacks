---
type: Defect
title: Flash does not verify what is running afterwards, and --bin checks the wrong source
description: After flashing, reconnect checks only log the sync block; they never compare build ID or version with the file flashed. With --bin, the source scan reads the current tree, not the binary.
tags: [tooling,safety]
status: draft
confidence: read from code
generated: { by: claude-code/claude-sonnet-5-5, at: 2026-11-19T00:23:42Z }
sources:
  - resource: ../../tools/lb_flash.py
---

# Problem

1. `verify_connect` prints "SWD ok, sync block at ..." and nothing more. If the flash silently left old firmware running, all three reconnect checks still pass and the build is recorded as canary-tested.
2. `flash --bin FILE` runs `cmd_check` on the sketch source in the working tree, which may be unrelated to `FILE`, and `check_binary(None, ...)` skips the ELF symbol check.

# Fix

- After each reconnect, compare the running block's firmware version, build ID, dirty flag and model with the header embedded in the flashed `.bin`, and fail on a mismatch.
- With `--bin`, require the binary's embedded build to match the tree that was source-checked, and use the sibling `.elf` for the symbol check when it exists.

# Resolution

Fixed on branch `sbx/jolly-shannon/02-review-doc-and-fixes`. `verify_connect` now returns the running unit's header and `check_running_build` compares firmware version, wire format, build ID and dirty flag with the header embedded in the flashed `.bin` after each of the three reconnects; a mismatch fails the flash and no canary is recorded. `flash --bin` refuses a binary stamped with a commit other than the checked-out one, warns about a dirty-tree build, and runs the symbol check on the sibling `.elf` when it exists. A binary without a header (or a tree without git) is not compared, with a warning. Not covered: the model id (it is not in the fixed header) and a dirty tree whose contents changed after the build.
