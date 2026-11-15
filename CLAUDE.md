# Instructions for coding agents

## Pull requests: sandbox fork only

This repository (`studcavity/Vape-Hacks`) is a sandbox fork of the original project at `SwiggityCricket/Vape-Hacks`.

- **Never open a pull request, issue, or comment against `SwiggityCricket/Vape-Hacks`** (the upstream/original repository). This applies to all work, including the `lightning_bugs` project.
- PRs may only target `studcavity/Vape-Hacks`. With `gh`, always pass `--repo studcavity/Vape-Hacks` explicitly; `gh pr create` on a fork can otherwise default to the upstream parent.
- Never push to, or add as a push remote, any upstream repository.

## Compiled binaries: don't commit them by default

Build outputs (`.elf`, `.hex`, `.map`, `.bin`, `.o`, `build/`) are generated and are not tracked (`*.bin` is git-ignored). Do not `git add` them.

Only commit a compiled binary if one of these is true:

- The user has explicitly told you to.
- It is the **only copy of code that cannot be regenerated**, such as a flash dump read from a device whose source we don't have (e.g. `backup_flash.bin`). Even then, **ask the user before committing it**.

If a build produces binaries inside the tree, add them to `.gitignore` instead of committing them.
