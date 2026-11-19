## 2026-11-19

- Shelved the automatic low-battery sleep; the firmware now sleeps only when the slide switch is at its off pole. `lightning-bugs/power-policy.md` keeps the shelved design and its constants.
- Converted the lasting parts of `toolchain.md`, `swd-recovery.md` and `py32c642-prior-art.md` into `tooling/` and `references/`; linked the migrated code-review bundle from `lightning-bugs/`. The 2026-11-17 checkpoint was only mined for the canary's option bytes.
- `references/pdf-sources.md`: noted that `poppler-utils` is pre-installed once the deps-file change merges.
- Created the bundle: hardware, display, firmware, lightning-bugs, tooling and references.
- Recorded the first PDF findings (UID, factory config, Vrefint range) in `references/`.
