# Test plan: USB passthrough in claude_sandbox, for both probe stacks

Most of this runs on the **host**, not inside the sandbox: only the host can attach USB. Updated
against the launcher at `claude_sandbox` commit `09058a4`, where passthrough is implemented (see the
status table in `USB_PASSTHROUGH_PLAN.md`). The launcher's own README says USB attachment is **not yet
verified against real incus and hardware**, so this is the first real test, for both stacks:

| | Stack A | Stack B |
|---|---|---|
| Probe | Raspberry Pi Pico, debug-probe (CMSIS-DAP) firmware | FTDI FT232R USB-UART adaptor |
| USB ID | `2e8a:000c` | `0403:6001` |
| Request name in `claude_sandbox_host.yaml` | `pico-probe` | `ft232r-adaptor` |
| pyocd selection | automatic | opt-in: `--probe ft232r:` or `PYOCD_FT232R_AUTODETECT=1` |

What remains overall, in order, is in `REMAINING_WORK.md`.

Throwaway branch. Record each result for **both** stacks (Vape-Hacks `CLAUDE.md`, "Probe parity"); put
FT232R findings in `lightning_bugs/probes/ft232r/README.md`.

## 1. Launcher
- Use the launcher from `studcavity/claude_sandbox` `main` (or a newer commit), on the host. Use
  `--cli incus` if that is what you run (the default is `lxc`); your user must be able to run
  `incus config device add`.
- The old `put_file` `/dev/stdin` bug is fixed in the launcher, so repos with `binaries:` or `scripts:`
  work again. The default base image is now `images:ubuntu/26.04`.

## 2. Check the hardware on the host first
- **Pico:** `lsusb | grep 2e8a` shows `2e8a:000c`. BOOTSEL mode is `2e8a:0003`, other firmware differs.
  Wire it to the target's SWD pins (PA13, PA14); use a unit you can power-cycle.
- **FT232R:** `lsusb | grep 0403:6001`. Wire it per `lightning_bugs/probes/ft232r/README.md` (330 to
  470 ohm bridge between TXD-side `SWDIO_OUT` and CTS-side `SWDIO_IN`, I/O jumper at 3.3 V, common
  ground). It will show up on the host as `/dev/ttyUSB*` (the `ftdi_sio` driver). Nothing on the host
  may be using it (`screen`, `minicom`, a host `pyocd`).
- **Plug in only one FT232R.** `0403:6001` is the generic ID of every FT232R adaptor, and the launcher
  attaches every host device with an approved ID.
- Nothing on the host may be holding the Pico (host `pyocd`, `openocd`).

## 3. Launch with the flag, one stack at a time (safest)

    ./claude_sandbox.py --repo studcavity/Vape-Hacks --cli incus --usb 2e8a:000c      # stack A
    ./claude_sandbox.py --repo studcavity/Vape-Hacks --cli incus --usb 0403:6001      # stack B

In the sandbox:
- `CLAUDE.md` has a `## Host hardware (USB)` section with `Devices for this launch:` listing the device
  as "attached and visible", and the exact `config device add ... mode=0660` command. The other device
  (requested by the repo, not approved) says "requested but **not approved**".
- `ls -l /dev/bus/usb/*/*` shows a node owned by `ubuntu`, mode 0660.
- **Stack A:** `pyocd list` shows the CMSIS-DAP probe.
- **Stack B:** `.venv/bin/python -m pyocd_ft232r` lists the adaptor, and
  `PYOCD_FT232R_AUTODETECT=1 .venv/bin/pyocd list` shows it as `ft232r:`.
  `.venv/bin/python -m pyocd_ft232r check` should exit 0 when the bridge is wired.
  **Unverified:** whether the host's `ftdi_sio` driver lets the sandbox claim the interface. If the
  adaptor is listed but `check` cannot open it ("could not claim interface" or a permission error),
  unload `ftdi_sio` on the host (`sudo modprobe -r ftdi_sio`), relaunch, and record the outcome.
- Unplug and replug on the host: the device reappears. Relaunch with it unplugged: `CLAUDE.md` says
  "attached but not visible".
- Exit: the container is gone and the host can use the device again (for the FT232R, check
  `/dev/ttyUSB*` returns). A launch without any USB option has no `/dev/bus/usb`.

## 4. The host file (already on Vape-Hacks `main`: both devices are requested)
Do **not** put `usb:` in `claude_sandbox_deps.yaml`: the launcher's deps schema rejects it and aborts the
launch. Requests belong only in `claude_sandbox_host.yaml`. Then, per approval path:
- Non-interactive, no flags (`</dev/null`): nothing attached; `CLAUDE.md` says both are "requested but
  not approved".
- Interactive: one `Attach? [y/N]` prompt per device, showing the vid:pid and the repo's description
  (untrusted). Answer `y` for one and `N` for the other, and confirm only that one is attached.
- Allowlist `~/.config/claude_sandbox/usb_allow` (mode 0600 or 0644, owned by you). Try:
  `2e8a:000c`, then `0403:6001 studcavity/Vape-Hacks` (repo-scoped), then a line for another repo and
  confirm it does **not** match. A group- or world-writable file must be refused.
- `--no-usb` alongside `--usb`: nothing attached.
- Both approved at once: both attached, both listed, and the two stacks are usable in one sandbox.

## 5. In the new sandbox
- Nothing from the previous sandbox survives, but `lightning_bugs/tools/setup.sh` now runs by itself
  from `setup:` in `claude_sandbox_deps.yaml` at every launch (no manual run). `CLAUDE.md` lists
  "Setup results this launch"; it should say succeeded. It runs with approved devices already attached
  and does not touch them.
- `lsb_release -a` says 26.04 (the launcher default). `.venv/bin/pyocd --version` is 0.46.1 and
  `pyftdi` is 0.57.2 (`lightning_bugs/constraints.txt`).
- Then `export PATH="$HOME/.local/bin:$PWD/lightning_bugs/.venv/bin:$PATH"`.

## 6. Before the first real flash
- `lb_flash.py` only allows a sealed unit after the same build passes on a canary unit
  (`flash --canary`). Nothing has run on a device yet.
- First hardware test is read-only, per stack: Pico, `pyocd list` then attach to the target with no
  flash. FT232R, follow the bring-up checklist in `lightning_bugs/probes/ft232r/README.md`
  (wiring check, then a read-only attach, before any write). The plugin has only run against a
  simulation, and its sample lag and maximum clock are unverified.
