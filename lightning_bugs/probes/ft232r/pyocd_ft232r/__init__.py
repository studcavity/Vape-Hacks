"""pyOCD probe plugin: SWD over an FTDI FT232R in synchronous bit-bang mode.

Layers (each testable without hardware):
  wire.py       pin map and the bit stream: SWD bits <-> bit-bang bytes
  swd.py        SWD transactions on top of the bit stream (queue, ACK, parity, recovery)
  transport.py  the FTDI device (pyftdi) plus the loopback self-test/calibration
  probe.py      the pyOCD DebugProbe and plugin that tie them together
"""

# pyOCD loads probe plugins while it is itself being imported, and that import pulls in
# pyocd_ft232r.probe. If our modules were the *first* thing to import pyOCD, that would be circular
# (probe.py half-initialised when pyOCD asks for FT232RProbePlugin). Importing pyOCD here, before any
# submodule runs, makes the order the same whichever way the package is reached.
import pyocd  # noqa: E402
_PYOCD = pyocd           # (used, so linters do not drop the import)
