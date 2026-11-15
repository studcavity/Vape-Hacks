# Plan: USB device passthrough for claude_sandbox

Self-contained: paste everything below the line into a Claude Code session in the
`claude_sandbox` repo. Throwaway branch, not for merging into Vape-Hacks `main`.

---

## Task: add opt-in USB passthrough (`--usb VID:PID`) to the launcher

### Why
Sandboxed sessions can't reach USB hardware: `/dev/bus/usb` doesn't exist in the
container. The first use case is the Vape-Hacks `lightning_bugs` project, which
flashes and syncs PY32F030 chips over SWD with `pyocd` through a Raspberry Pi
Pico debug probe (CMSIS-DAP, USB vendor 2e8a, product 000c). Without passthrough
the session can only run simulated tests, never real hardware.

### Design
Add a repeatable CLI flag `--usb VID:PID` (hex, e.g. `--usb 2e8a:000c`). For each
one, after the container launches and before deps/credentials are installed, run:

    <cli> config device add <name> usb-<vid>-<pid> usb \
        vendorid=<vid> productid=<pid> uid=1000 gid=1000 mode=0660

(`lxc` and `incus` take the same arguments. The `uid`, `gid` and `mode` options
make the node usable by the unprivileged `ubuntu` user, matching `UID` in
`sandbox_containers.py`. No udev rules are needed in the container.) Incus
re-attaches a USB device matched by vid:pid after it re-enumerates, which matters
because probes and targets reset and re-enumerate. The device is removed with the
ephemeral container.

### Files to change
- `sandbox_containers.py`: add `Container.add_usb(vid, pid)` that runs the
  command above through `run([...])` as an argv list (no shell).
- `claude_sandbox.py`:
  - `build_parser`: `--usb` with `action="append"`, `metavar="VID:PID"`, default
    `[]`, help text saying it exposes that host USB device to the sandbox.
  - a small pure function `parse_usb(spec)` that accepts only
    `^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$`, lowercases it, and raises `SystemExit` /
    `argparse.ArgumentTypeError` otherwise. **Both IDs are required**: reject
    vendor-only or wildcard forms so a launch can't pass through every device.
  - `Sandbox.launch`: after `wait_network()`, loop over `self.args.usb` and call
    `self.box.add_usb`. Log each one (`log(f"passing USB device {vid}:{pid}")`).
  - validate the specs in `main`, before any container is created, so a typo
    fails fast.
- `sandbox_CLAUDE.md`: a short section, rendered only when `--usb` was given,
  listing the passed-through devices so the in-sandbox session knows about them
  (extend `render_claude_md` and its template placeholders; note `$$` escaping).
- `claude_sandbox_deps.yaml` / `README.md`: document `--usb`, and note that
  repos wanting `lsusb` should list `usbutils` under `apt:`.

### Behaviour notes to handle
- The image cache (`ensure_base_image`, `ensure_deps_image`) must be unaffected:
  devices are attached at launch, never baked into an image.
- If the device isn't plugged in on the host, `config device add` still succeeds
  (it attaches when the device appears). Don't treat that as an error, but log a
  hint that the device wasn't found if the host `lsusb` shows no match (optional).
- A Pico in BOOTSEL mode shows up as 2e8a:0003, and some probes use other IDs;
  the user supplies the IDs, the launcher doesn't guess.
- Don't make `--usb` the default for any repo; it must be an explicit flag on
  every launch.

### Security and isolation trade-offs
- This is the first thing that exposes host hardware to the sandbox. The container
  gets raw access to exactly one vid:pid, nothing else. A USB device can run
  firmware that attacks its host or the container, and a debug probe can
  read/write any target it's wired to. Only pass devices you own and trust.
- Exposure is limited by: opt-in flag, mandatory full vid:pid, ephemeral container
  (device detached on teardown), no changes to the network, mounts or secrets.
- It does not weaken credential handling; secrets still go over stdin, and
  `install_deps` still runs before credentials exist.
- The mode is 0660 with the `ubuntu` uid/gid, never 0666.
- State clearly in the README that two concurrent sandboxes can't share one
  device (the second `add` takes it from the first or fails, depending on the
  incus version), and that the host must not be using it (e.g. a host `pyocd`
  holding the probe).

### Tests (pytest, per the repo's CLAUDE.md; no real containers)
- `tests/test_containers.py`: `add_usb` builds the exact argv for both `lxc` and
  `incus` (use the existing `calls` fixture).
- `tests/test_claude_sandbox.py`:
  - `parse_usb` accepts `2e8a:000c` and `2E8A:000C` (normalised to lowercase) and
    rejects `2e8a`, `2e8a:`, `:000c`, `2e8a:*`, `xyz1:0000`, `2e8a:000c;rm`, and
    5-digit forms.
  - launch calls `add_usb` once per `--usb`, before `install_deps`, and not at all
    with no flag (extend `FakeBox` in `tests/conftest.py` with `add_usb`).
  - `render_claude_md` real-template test still passes with and without devices.
- Run `python -m pytest`, `python -m pyflakes *.py tests/`, `shellcheck run.sh`
  before committing, and say in the commit message that an end-to-end launch with
  real hardware was done by hand (or wasn't).

### Verification by hand (needs a host with incus and the probe plugged in)
1. `lsusb | grep 2e8a` on the host to confirm the IDs.
2. `./claude_sandbox.py --repo <owner>/<repo> --usb 2e8a:000c --shell`
3. In the sandbox: `ls -l /dev/bus/usb/*/*` shows one node owned by `ubuntu`
   with mode 0660; `lsusb` (with `usbutils`) lists the probe.
4. `pyocd list` (from the Vape-Hacks `lightning_bugs/.venv`) shows the CMSIS-DAP
   probe. Unplug and replug it and confirm it reappears.
5. Exit the sandbox and confirm that `incus list` shows the container gone and the
   host can use the probe again.
6. Launch without `--usb` and confirm `/dev/bus/usb` is still absent.

### Out of scope
Network-based alternatives (`pyocd gdbserver` on the host), Bluetooth/serial
passthrough, and per-repo auto-detection of devices.
