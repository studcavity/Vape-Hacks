# pyocd-ft232r: SWD through an FT232R USB-UART adaptor

> **Probe parity (read this first).** This repo supports **two probe stacks** for now:
> **A.** a Raspberry Pi Pico (USB `2e8a:000c`) running debug-probe (CMSIS-DAP) firmware, using pyocd's built-in drivers, and
> **B.** an FTDI **FT232R** adaptor (USB `0403:6001`, select with `--probe ft232r:`) using this plugin. Any change to the Lightning Bugs host tools,
> setup, tests, docs or sandbox/USB configuration **must be made for both stacks** so they stay at parity.
> The tools (`lb_flash.py`, `lb_sync.py`) must stay probe-agnostic: they talk only to pyocd, and the probe
> is chosen with `--probe`. See "Probe parity" in the repo's `CLAUDE.md`.

A [pyOCD](https://pyocd.io) probe plugin that speaks SWD over an FT232R in synchronous bit-bang mode.
The FT232R has no MPSSE, so it cannot be a fast probe, but it works with the project's tools unchanged.

## Wiring

```
FT232R                                   target (PY32F030)
 TXD  (D0)  SWCLK ----------------------- SWCLK  (PA14)
 RXD  (D1)  SWDIO_OUT --[ 330-470 ohm ]--+
 CTS# (D3)  SWDIO_IN ---------------------+- SWDIO  (PA13)
 GND -------------------------------------- GND
```

- The **resistor is required**: it lets one output pin and one input pin share SWDIO, because the chip
  cannot switch direction mid-frame. The target's driver overpowers the resistor when it sends a 0.
- Set the adaptor's I/O voltage jumper to **3.3 V**. Do not power the target from the adaptor if a
  battery is connected. Common ground only.
- Other pins: `-O ft232r.pins=swclk=4,swdio_out=5,swdio_in=6[,nreset=2]` or `PYOCD_FT232R_PINS=...`
  (D0..D7 = TXD, RXD, RTS#, CTS#, DTR#, DSR#, DCD#, RI#). `nreset` is optional and push-pull: put about
  1 kohm in series.

## In a claude_sandbox

The repo requests both probes in `claude_sandbox_host.yaml`; nothing is attached until the host user
approves it (`--usb 0403:6001`, the launcher's prompt, or the allowlist `~/.config/claude_sandbox/usb_allow`).

- `0403:6001` is the generic ID of **every** FT232R serial adaptor, and the launcher attaches every host
  device with an approved ID. Approve it only when no other FT232R on the host matters. Plug in just the
  probe adaptor, or scope the allowlist line to this repo (`0403:6001 studcavity/Vape-Hacks`).
- Unverified: whether the host's `ftdi_sio` driver (which makes the adaptor `/dev/ttyUSB0`) lets the
  sandbox claim the interface. Try `python -m pyocd_ft232r` first; if it finds the adaptor but `check`
  cannot open it, unload `ftdi_sio` on the host (`sudo modprobe -r ftdi_sio`) and record the outcome here.

## Using it

The adaptor is a plain USB-serial device, so it is **only offered when you ask for it** (a tool run
without `--probe` never wiggles the pins of an adaptor plugged into something else):

```sh
python -m pyocd_ft232r                 # list adaptors (USB 0403:6001)
python -m pyocd_ft232r check           # wiring self-test, no target needed
pyocd list -u ft232r:                  # first FT232R;  ft232r:<serial> picks one
python3 tools/lb_flash.py --probe ft232r: build
python3 host/lb_sync.py --probe ft232r: sync
PYOCD_FT232R_AUTODETECT=1 pyocd list   # list FT232Rs like any other probe
```

Options: `ft232r.pins`, `ft232r.safe` (one transaction per USB round trip; slow, never clocks a frame
past an error), `ft232r.latency_timer` (default 1 ms). Installed into the project venv by
`tools/setup.sh`; manually: `pip install -e lightning_bugs/probes/ft232r`.

## How it works (and what is not verified)

`wire.py` turns SWD bits into bit-bang bytes (two per clock), `swd.py` queues register transactions and
runs them as one exchange (so a `read32` is one USB round trip), `transport.py` drives pyftdi and
**measures the chip's sample lag with a loopback test at open** (so it does not depend on an undocumented
FIFO detail), `probe.py` is the pyOCD `DebugProbe`.

Tested here only against a pin-level simulation of an SW-DP and a MEM-AP (`lightning_bugs/tests/ft232r/`),
including pyOCD's own `DebugPort`/`MEM_AP` and `lb_sync.Device`. **Not yet verified on hardware:**

1. The real sample lag and that calibration accepts it (`python -m pyocd_ft232r check`).
2. The maximum reliable clock (`MAX_SWD_HZ` = 500 kHz is a guess; the default is 250 kHz).
3. Real-target behaviour on WAIT/FAULT. After one, a pipelined batch is abandoned and the line is flushed
   with idle cycles. A WAIT followed by accepted frames is reported (not replayed); use `ft232r.safe=1`
   if you see "cannot replay safely".
4. Sync accuracy: round-trip jitter should be similar to a Pico (both are USB full speed), but it has
   not been measured.

## Bring-up checklist (first time on hardware)

1. `python -m pyocd_ft232r` lists the adaptor; `check` prints OK. A failure means the resistor bridge,
   pin numbers or voltage jumper.
2. With the target wired: `pyocd list -u ft232r:` then `pyocd cmd -u ft232r: -t py32f030x8` and read
   a RAM word. Read-only first; no flash.
3. Run `lb_sync.py --probe ft232r: status` before anything that writes.
4. Flashing still follows the canary policy in `tools/lb_flash.py`.
