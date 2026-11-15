# Plan: USB device passthrough for claude_sandbox

Self-contained: paste everything below the line into a Claude Code session in the
`claude_sandbox` repo. Throwaway branch, not for merging into Vape-Hacks `main`.

---

## Task: add opt-in USB passthrough, declared by flag or in `claude_sandbox_deps.yaml`, with self-discovery in the sandbox's CLAUDE.md

### Why
Sandboxed sessions can't reach USB hardware: `/dev/bus/usb` doesn't exist in the
container. The first use case is the Vape-Hacks `lightning_bugs` project, which
flashes and syncs PY32F030 chips over SWD with `pyocd` through a Raspberry Pi
Pico debug probe (CMSIS-DAP, USB 2e8a:000c). Without passthrough the session can
only run simulated tests. Separately, a session shouldn't have to guess what it
was given: the sandbox CLAUDE.md should say which devices were attached, how, and
how to check.

### Security model (decide this first; it shapes everything else)
`claude_sandbox_deps.yaml` is **repo-controlled**, and a commit to it affects
future launches. USB passthrough exposes host hardware, so a repo must never be
able to grant itself a device just by declaring it. Therefore:

- The yaml `usb:` section is a **request**, not a grant. Declaring a device there
  attaches nothing by itself.
- A request is honoured only when the **host user approves it**, by one of:
  1. `--usb VID:PID` on the command line (explicit grant, no yaml needed);
  2. `--allow-usb` (approve exactly the devices the yaml requests, after the
     launcher prints them and, if stdin is a TTY, asks `[y/N]`; no TTY and no
     flag means skip them and log that);
  3. an optional host allowlist file `~/.config/claude_sandbox/usb_allow`
     (one `vid:pid` per line, next to `oauth_token` in `claude_sandbox.py`'s
     config dir): yaml requests matching a line are attached without a prompt.
- Unapproved requests are not an error: the launch proceeds without the device,
  and the sandbox CLAUDE.md says the device was requested but **not attached**
  (so the session can tell the user how to approve it rather than failing
  mysteriously).
- Full `vid:pid` is mandatory everywhere. No vendor-only or wildcard forms.

### Design

**1. CLI.** Repeatable `--usb VID:PID` (hex, e.g. `--usb 2e8a:000c`) plus
`--allow-usb` and `--no-usb` (ignore all USB, flag and yaml alike).

**2. yaml schema** (`sandbox_deps.py`; keep the strict schema, so unknown keys are
still errors). Add an optional list:

    usb:
      - name: pico-probe            # [A-Za-z0-9._+-], becomes the device name
        vendor_id: "2e8a"           # 4 hex digits, quoted so yaml doesn't make it an int
        product_id: "000c"
        description: Raspberry Pi Pico debug probe (CMSIS-DAP), SWD to the target
        tools: [pyocd]              # optional, free text hints for the session

Validate: `name` pattern and uniqueness, both IDs match `^[0-9a-fA-F]{4}$`
(normalised to lowercase), `description` is a short string with no newlines
(it is later rendered into CLAUDE.md; cap the length, e.g. 200 chars, and escape
`$` for `string.Template`), at most a handful of entries (say 8).
**Important:** `usb` must be excluded from `cache_key()` and from the baked
image; it describes a per-launch attachment, not installed content. Add a test
that changing `usb` doesn't change the key. Old launchers reject the new key (the
whole file is invalid), so mention in the README that repos using `usb:` need a
launcher with this change.

**3. Attach.** Merge flag devices and approved yaml requests (flag wins on
duplicates, description from yaml if there is one). In `Sandbox.launch`, after
`wait_network()` and before `install_deps`, for each one run, as an argv list
through `run([...])` (no shell):

    <cli> config device add <container> usb-<vid>-<pid> usb \
        vendorid=<vid> productid=<pid> uid=1000 gid=1000 mode=0660

(`lxc` and `incus` take the same arguments; uid/gid match `UID` in
`sandbox_containers.py`, and the 0660 mode with the `ubuntu` owner means no udev
rules are needed in the container.) Add `Container.add_usb(vid, pid)`. Incus
re-attaches the device after it re-enumerates, which probes and targets do on
reset. The device goes away with the ephemeral container.

**4. Self-discovery, host side.** After attaching, the launcher probes what the
container actually sees, so CLAUDE.md states facts, not intentions. Add to the
existing container probe (`parse_probe`, which parses `key=value` lines) a
`usb=` line built **without `lsusb`** (it may not be installed) by reading sysfs:

    for d in /sys/bus/usb/devices/*; do [ -r $d/idVendor ] && \
      echo "$(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/product 2>/dev/null)"; done

Extend `parse_probe` to return `usb_present` (a set of `vid:pid` seen). Compare
against what was attached: each device is rendered as `attached and visible`,
`attached but not visible (not plugged in on the host, or already used by
another process there)`, or `requested but not approved`.

**5. Self-discovery, in the sandbox CLAUDE.md** (`sandbox_CLAUDE.md`, rendered by
`render_claude_md`). Add a `$usb` placeholder that expands, when any device was
requested or attached, to a section like (keep it short, in the file's existing
style, and escape `$$`):

    ## USB devices
    These host USB devices were passed into this sandbox (launcher flags and/or
    `usb:` in `claude_sandbox_deps.yaml`):
    - `pico-probe` 2e8a:000c, Raspberry Pi Pico debug probe (CMSIS-DAP): attached and visible
    - `foo` 1234:abcd, ...: requested but not approved by the host user
    Attached with: `incus config device add <container> usb-2e8a-000c usb vendorid=2e8a productid=000c uid=1000 gid=1000 mode=0660`
    (so the nodes under /dev/bus/usb are owned by `ubuntu`, mode 0660).
    Discover and check:
    - `ls -l /dev/bus/usb/*/*`; `for d in /sys/bus/usb/devices/*; do ...; done`
      (give the one-liner), or `lsusb` if usbutils is installed (add `usbutils` to
      `apt:` in the deps file)
    - `pyocd list` for CMSIS-DAP probes
    If a device is "not visible", it is probably unplugged on the host or in use
    by a host process; ask the user. You cannot attach devices from inside the
    container (the `config device add` runs on the host). If you need one that
    isn't listed, follow "Missing sandbox capabilities": add a `usb:` request to
    `claude_sandbox_deps.yaml` (commit and push), and tell the user to relaunch
    with `--allow-usb` (or `--usb VID:PID`).
    The container is ephemeral; unplugging/replugging reattaches by vid:pid.

With no USB devices the section is omitted entirely (and the existing
`test_render_claude_md_real_template` must still pass, with no unsubstituted
placeholders). Also update the template's existing "Missing sandbox
capabilities" text and the `claude_sandbox_deps.yaml` format block so the session
knows `usb:` exists and what its fields mean, including that it is only a request.

**6. Docs.** README: the `--usb`, `--allow-usb`, `--no-usb` flags, the `usb:`
yaml section with the example above, the allowlist file, the approval model, and
that two sandboxes can't share one device and the host must not be using it (for
example a host `pyocd` holding the probe).

### Behaviour notes
- Image caches (`ensure_base_image`, `ensure_deps_image`) are unaffected: devices
  are attached at launch only, never baked in.
- `config device add` succeeds even if the device isn't plugged in yet (it
  attaches when it appears); that is why the sysfs probe, not the add, decides
  "visible".
- A Pico in BOOTSEL mode is 2e8a:0003, and other probes differ; the user or the
  repo supplies the IDs, the launcher doesn't guess.
- Nothing is attached by default for any repo.

### Security and isolation trade-offs
- First feature exposing host hardware to the sandbox. The container gets raw
  access to exactly the approved vid:pid, nothing else. USB firmware can attack
  its host or the container, and a debug probe can read/write whatever it's wired
  to. Only pass devices you own and trust.
- Because the yaml can only request, a malicious or mistaken commit to a repo's
  deps file can't silently expose a device; the host user's flag, prompt or
  allowlist is the grant. The prompt shows the vid:pid and the repo-supplied
  description, which is untrusted text: print it escaped/truncated and show the
  vid:pid prominently.
- `description` flows into CLAUDE.md, so validate/escape it (newlines, `$`,
  markdown fences) to prevent prompt injection from the yaml into the session's
  instructions beyond what the deps file already allows.
- No changes to network, mounts or secrets. `install_deps` still runs before any
  credential exists. Mode is 0660 with the `ubuntu` uid/gid, never 0666.

### Tests (pytest, per the repo's CLAUDE.md; no real containers)
- `tests/test_containers.py`: `add_usb` builds the exact argv for `lxc` and
  `incus`.
- `tests/test_deps.py`: valid `usb:` parses and normalises; rejects bad IDs, bad
  or duplicate names, newline/oversized description, unknown sub-keys, too many
  entries; `cache_key` is unchanged by `usb`.
- `tests/test_claude_sandbox.py`:
  - flag parsing (accepts `2e8a:000c` / uppercase, rejects `2e8a`, `2e8a:`,
    `:000c`, `2e8a:*`, `xyz1:0000`, `2e8a:000c;rm`, 5 digits);
  - the approval matrix: flag grants; yaml alone grants nothing; yaml plus
    `--allow-usb` grants; yaml plus allowlist match grants; `--no-usb` grants
    nothing; no TTY and no flag skips with a log line;
  - `add_usb` is called per approved device, before `install_deps`, not at all
    otherwise (extend `FakeBox` in `tests/conftest.py`);
  - `parse_probe` reads the `usb=` data; `render_claude_md` renders each of the
    three states, includes the exact attach command, escapes `$` in descriptions,
    and omits the section with no devices.
- Run `python -m pytest`, `python -m pyflakes *.py tests/`, `shellcheck run.sh`
  before committing; say in the commit message whether an end-to-end launch with
  real hardware was done by hand.

### Verification by hand (host with incus and the probe plugged in)
1. `lsusb | grep 2e8a` on the host.
2. With a repo whose deps file has the `pico-probe` request: launch with no flags
   and confirm the probe is **not** attached and CLAUDE.md says "requested but
   not approved". Relaunch with `--allow-usb` (then again with
   `--usb 2e8a:000c` and a bare repo, and once with the allowlist file).
3. In the sandbox: CLAUDE.md lists the device as "attached and visible" with the
   attach command; `ls -l /dev/bus/usb/*/*` shows a node owned by `ubuntu`, mode
   0660; `pyocd list` shows the CMSIS-DAP probe. Unplug and replug and confirm it
   returns.
4. Launch with the probe unplugged: CLAUDE.md says "not visible".
5. Exit and confirm the container is gone and the host can use the probe again;
   launch without any USB option and confirm `/dev/bus/usb` is absent.

### Out of scope
Network-based alternatives (`pyocd gdbserver` on the host), Bluetooth/serial
passthrough, and auto-detecting devices.
