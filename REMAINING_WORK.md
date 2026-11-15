# What is left to do

State of `studcavity/Vape-Hacks` `main` as of `cbb9dcf` (CI green on Ubuntu 24.04 and 26.04 runners,
Python 3.10/3.12/3.14). Everything below needs real hardware or a real 26.04 sandbox launch, so none of
it could be finished or verified from inside a sandbox. Throwaway branch; delete it when this list is done.

Companion docs on this branch: `USB_TEST_PLAN.md` (step-by-step host checks) and `USB_PASSTHROUGH_PLAN.md`
(the original design, now marked implemented).

## Already done (do not redo)
- Both probe stacks supported and requested: Pico `2e8a:000c`, FT232R `0403:6001`
  (`claude_sandbox_host.yaml`, plugin in `lightning_bugs/probes/ft232r/`, parity rule in `CLAUDE.md`).
- 26.04 audit: apt names, `setup.sh`, firmware build and the whole test suite pass on a real 26.04
  userland (Python 3.14); CI runs both Ubuntu releases. The launcher already defaults to 26.04.
- `pyocd==0.46.1` and `pyftdi==0.57.2` pinned in `lightning_bugs/constraints.txt`.
- `setup.sh` runs from `setup:` at every sandbox launch, and on your own machine only with
  `--i-know-this-modifies-my-system` (everything stays under `lightning_bugs/.tools` and `.venv`).

## 1. You, on the host with hardware (in this order)

1. **Pico, when it arrives.** Flash the Pico with debug-probe (CMSIS-DAP) firmware (BOOTSEL shows as
   `2e8a:0003`; once flashed it should show `2e8a:000c`), wire it to the target's SWD pins
   (PA13/PA14), then run `USB_TEST_PLAN.md` sections 2 and 3 for stack A.
2. **FT232R wiring and the plugin's first real run.** Wire the resistor bridge and 3.3 V jumper per
   `lightning_bugs/probes/ft232r/README.md`, then its bring-up checklist: `python -m pyocd_ft232r` lists
   it, `check` prints OK, then a read-only RAM read, then `lb_sync.py --probe ft232r: status`. Nothing
   writes yet. The plugin has only ever run against a simulation.
3. **USB passthrough into the sandbox, per probe** (`USB_TEST_PLAN.md` sections 3 and 4). The launcher's
   own README says this path is unverified against real incus and hardware, so this is its first test.
   Specifically for the FT232R: does the host's `ftdi_sio` driver let the sandbox claim the adaptor? If
   not, `sudo modprobe -r ftdi_sio` on the host and record it.
4. **Approve the right things.** Use `--usb`, the prompt, or a repo-scoped allowlist line
   (`0403:6001 studcavity/Vape-Hacks`). `0403:6001` is every FT232R's ID and the launcher attaches every
   match, so keep other FT232R adaptors unplugged while testing.
5. **First flash, canary first.** `lb_flash.py` only allows a sealed unit after the same build passed
   `flash --canary` on a unit you can recover. Nothing has ever been flashed. Do it once per stack. The
   first hardware step is read-only, flashing comes after.
6. **Firmware checks on a real chip** (`lightning_bugs/README.md`, Status): confirm `uwTick` is the counter
   behind `millis()` (the tool refuses to sync if it is not about 1 kHz), then measure real drift over
   4 to 6 hours with `status` and replace the README's estimates with measured numbers.
7. **A Pi 5 as a free arm64 check** (optional): run `lightning_bugs/tools/setup.sh
   --i-know-this-modifies-my-system` there. The `aarch64` branch of the script (the `Linux_ARM64`
   `arduino-cli` asset) has never been run; the 0.33.0 checksum is fetched and checked at run time.

## 2. Next sandbox session, once step 1 has results

- Write the results into `lightning_bugs/probes/ft232r/README.md`, replacing its "not yet verified" list:
  real sample lag, the real maximum clock (`MAX_SWD_HZ` = 500 kHz is a guess; default 250 kHz), real WAIT
  and FAULT behaviour, and sync jitter compared with the Pico.
- Fix whatever hardware shows (calibration rejecting the real lag, timing, retries). **Every change goes
  to both stacks, or the gap is recorded in the plugin README** (`CLAUDE.md`, "Probe parity").
- First launch on the 26.04 image: check "Setup results this launch" in the sandbox `CLAUDE.md` says
  succeeded, then regenerate `last_generated` and `platform` in `claude_sandbox_deps.yaml` (they still
  say Ubuntu 24.04.5 because that is the OS they were last generated on). The first launch will also
  rebuild the cached image, so it is slower.
- Update `USB_TEST_PLAN.md` and the plugin README with anything the host steps contradicted.

## 3. Optional, decide later
- **Pin the dependencies' dependencies** (`pyusb`, `libusb-package`, `cmsis-pack-manager`, `capstone`,
  and others) with a lock file. Only `pyocd` and `pyftdi` are pinned today; a lock is Python- and
  architecture-specific, so it costs maintenance.
- **A launcher change in `claude_sandbox`:** let a USB approval also match a serial number, so approving
  an FT232R does not expose every FT232R on the host. Not drafted; ask for the plan if wanted.
- **Optional firmware features** from `lightning_bugs/README.md`: store the rate correction in flash,
  add a hardware resync input, or fit a 32.768 kHz crystal if drift is too large.
- **Delete this branch** (`throwaway/usb-passthrough-plan`) once steps 1 and 2 are finished and the
  verified results are in the repo docs on `main`.
