# Test plan: USB passthrough in claude_sandbox

Most of this runs on the **host**, not inside the sandbox. The implementing
session can unit-test the launcher; only the host can attach USB.
Related: `USB_PASSTHROUGH_PLAN.md` (the implementation plan). Throwaway branch.

## 1. Run the new launcher from the host
- Check out the implementing session's `claude_sandbox` branch on the host and
  launch from that copy, not your installed one.
- That branch must also include the `put_file` `/dev/stdin` fix. Without it, repos
  with `binaries:` or `scripts:` entries still fail at the deps step.
- Use `--cli incus` if that's what you run (the default is `lxc`). The host user
  must be allowed to run `incus config device add`.

## 2. Check the hardware first (host)
- Plug in the Pico probe: `lsusb | grep 2e8a`. Expect `2e8a:000c`; other firmware
  or BOOTSEL mode shows other IDs (BOOTSEL is `2e8a:0003`).
- Nothing on the host may be holding the probe (host `pyocd`, `openocd`).
- Wire the probe to the target's SWD pins (PA13, PA14). The target must be a unit
  you can power-cycle.

## 3. Launch with the flag first (safest, repo yaml untouched)
    ./claude_sandbox.py --repo studcavity/Vape-Hacks --cli incus --usb 2e8a:000c
In the sandbox check:
- CLAUDE.md has a `## USB devices` section: "attached and visible", with the exact
  `config device add` command.
- `ls -l /dev/bus/usb/*/*` shows a node owned by `ubuntu`, mode 0660.
- `pyocd list` shows the CMSIS-DAP probe.
- Unplug and replug the probe on the host: it reappears.
- Relaunch with the probe unplugged: CLAUDE.md says "not visible".
- Exit: container gone, host can use the probe again. A launch without any USB
  option has no `/dev/bus/usb`.

## 4. yaml path (last, and careful)
- The launcher reads the deps file from the default branch (`main`) via the GitHub
  API, so a `usb:` section on a branch is not seen.
- **Do not put `usb:` on `main` until the new launcher is your everyday one.** The
  old launcher rejects unknown keys and aborts the whole launch.
- Then add the request to `claude_sandbox_deps.yaml` on `main`:

      usb:
        - name: pico-probe
          vendor_id: "2e8a"
          product_id: "000c"
          description: Raspberry Pi Pico debug probe (CMSIS-DAP), SWD to the target
          tools: [pyocd]

  and test: no flags (expect "requested but not approved", nothing attached);
  `--allow-usb` (prompt, then attached); the allowlist file
  `~/.config/claude_sandbox/usb_allow` containing `2e8a:000c`; `--no-usb`
  (nothing attached).
- Also restore the arduino-cli `binaries:` entry (checksum is in git history,
  commit c1f8dd1) and confirm `arduino-cli version` prints 0.33.0 on launch.

## 5. In the new sandbox
- Nothing installed in the previous sandbox survives. Run
  `bash lightning_bugs/tools/setup.sh` (~260 MiB). apt packages come from the
  deps file.
- Then: `export PATH="$HOME/.local/bin:$PWD/lightning_bugs/.venv/bin:$PATH"` and
  `pyocd list` should show the probe.

## 6. Before the first real flash
- `lb_flash.py` only allows a sealed unit after a build passes on a canary unit
  (`flash --canary`). Nothing has run on a device yet.
- First hardware test is read-only: `pyocd list` and attach to the target, no flash.
