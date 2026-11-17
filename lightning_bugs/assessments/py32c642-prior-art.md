# Prior art: PY32C642 in a Hayati Pro Ultra (grahamwhaley/py32c642_vape)

Source: <https://github.com/grahamwhaley/py32c642_vape> (README read at tree `5d82bc21`; the code, schematic and
datasheets in that repo were not read). Everything below is that author's report, not something we have tried.

**How close is it to us?** Similar, not the same. Same vendor (Puya), same core (Cortex-M0+), same kind of device
(a rechargeable vape with a display, a LiPo charger chip and an SWD port), and the same probe idea (a Raspberry Pi
Pico). Different chip: a PY32C642F15 (24 KB flash, 3 KB RAM, 20 pins) that no tool supports natively, whereas our
PY32F030x8 has a native pyocd target (`py32f030x8`) and a prior-art project of its own (see
`PY32F030EK28 - Geek Bar Pulse X Jam/README.md`). Different access: his SWD is on four labelled test points on the
board (V+, DA, CK, G-) after opening the case; ours is on the USB-C A5/B5 pins. Different probe firmware: he used
[free-dap](https://github.com/ataradov/free-dap) on the Pico, we use the Raspberry Pi `debugprobe` v2.3.1.

## What he found

1. **A bare wire connection did not work.** He wired the Pico straight to the SWD pins and neither
   [edbg](https://github.com/ataradov/edbg) nor `pyocd` could connect. The tools were told the chip was a
   `py32f002b`, because the C642 is not known to them.
2. **Pull-up and series resistors, plus a slower clock, fixed it.** He added both ("pullup and series resistors",
   citing Arm's
   [DSTREAM SWD signal notes](https://developer.arm.com/documentation/dui0499/k/arm-dstream-target-interface-connections/signal-descriptions/serial-wire-debug)),
   told the tools to run at **1 MHz**, "and voila". He does not give resistor values, and does not say what speed
   he started from or whether the clock alone would have worked, so how much each change contributed is not known.
3. **An extra utility is needed once after every power-up.** After powering the board, `pyocd` could not talk to
   it until he had run `edbg` once. That `edbg` command "effectively fails", but afterwards `pyocd` works until the
   next power cycle. He suspects a missing wake-up sequence and has not tracked it down:

   ```sh
   ./edbg -t py32f0 -c 5 -r                                                  # once per power-up; reports failure, still needed
   pyocd load ./build/blink.bin -v -v -v -t py32f002bx5 -Ofrequency=1000000
   ```

4. **Backup read.** The flash was not read-protected. He dumped it before changing anything with:

   ```sh
   pyocd cmd -v -t py32f002bx5 -Ofrequency=1000000 -c savemem 0x08000000 0x6000 flash.bin
   ```

   (0x6000 = 24 KB, that chip's flash size.) He re-flashed the original image several times afterwards.
5. **Power the board from the probe, not from the battery.** His battery was dead (about 0.3 V) and cut off. He
   suspects that, unless the SWD probe takes the target voltage as a reference input with level buffers, one should
   disconnect the battery and not use USB power while debugging, and power the board from the dongle instead.
6. **Units differ.** Of his four units, two had a corroded SWD pad or display, and one drew milliamps in stop mode
   instead of microamps. He concludes that a flat or corroded unit may already be faulty.

## What it may mean for us (inference, not tested)

- **Speed.** `lb_flash.py` and `lb_sync.py` already default to **500 kHz** (`--frequency`), below his 1 MHz. If our
  connection is flaky, go lower before anything else (`-f 100000`).
- **Resistors.** It agrees with the F030 prior art that series resistors and pull-ups were used when probing from a
  Pico, and that a bare connection is what failed for him. Neither project shows that a bare connection is
  impossible on every unit, so trying one remains your call. The RP2040 and PY32F030 voltage limits behind the
  series-resistor advice are in `lightning_bugs/README.md` ("Wiring the Pico to the unit").
- **The `edbg` step may not apply to us.** We have no evidence the F030 needs it: the F030 prior art flashed with
  plain `pyocd flash -t py32f030x8 -f 500000`. Treat it as a fallback if `pyocd list` sees the probe but a
  connection to the target fails after a power-up. `edbg` is a separate CMSIS-DAP tool; we have not installed it
  or checked that it works with the debugprobe firmware.
- **`savemem` is an alternative way to dump.** `lb_flash.py dump` reads flash through the pyocd Python API instead
  (two reads, compared, blank check). For the F030 the equivalent would be `-t py32f030x8` and `0x10000`.
- **Power source: the two projects pull in different directions.** He recommends powering the board from the probe
  and removing the battery. Our advice so far was to power the unit from its own battery and not connect the Pico's
  VBUS/VSYS, because at about 5 V (USB power) the PY32F030 input threshold (0.7 x VCC, about 3.5 V) is above the
  Pico's 3.3 V output. Those are different boards, and his is about test points, not USB-C pins, so neither
  advice overrides the other. If we ever power the F030 unit from the Pico's 3.3 V, check the unit still
  runs at that voltage (its operating range starts at 1.7 or 2.0 V by the datasheet) and that the charger chip and
  USB-C lines are not back-driven. Unresolved; do not do it on a unit you cannot afford to lose without checking.
- **Don't generalise from his units.** A dead battery, a corroded pad and a high stop-mode current are properties of
  his boards.

## Status

- [ ] Try a connection at the default 500 kHz and, if needed, lower
- [ ] If the probe sees the target only after something else touched it, try the `edbg` wake-up from item 3
- [ ] Decide on resistors / pull-ups once a bare connection has or has not worked
