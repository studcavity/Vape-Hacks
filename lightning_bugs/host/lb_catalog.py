"""
lb_catalog.py — the project's actual compatibility data, expressed with lb_compat.

To record a change, add to this file only:

  * a new wire-format minor that appends words      -> a FormatSpec in FORMATS (+ the struct in lb_sync.h)
  * a field whose meaning changed in firmware X.Y.Z -> a new, newer Variant on the feature that reads it
    (keep the old variant: units still running older firmware need it)
  * a new hardware model                            -> a Model in MODELS built from Traits; a marker
                                                       Trait + a Variant requiring HasTrait(...) only
                                                       where it computes something differently
  * a new way of reaching units                     -> a Transport in TRANSPORTS (and the traits of
                                                       the models reachable over it)
  * a command that needs something new              -> its entry in COMMANDS

Nothing is released yet (no unit has been flashed), so format 4.0 may still be amended; once a
unit has been flashed with a format, change it only by adding a minor.

Decoders take a Block (see lb_sync.py) and return plain data; they must not touch hardware, so
the same decoding works on a block that arrived by any transport.
"""
from __future__ import annotations

from lb_compat import (Access, Catalog, CommandNeeds, Feature, Fields, Firmware, FormatSpec, Formats, Model,
                       Trait, Transport, Variant)

U32 = 1 << 32
NO_TEMP = -(1 << 31)                     # LB_NO_TEMP in lb_sync.h


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - U32 if v & 0x80000000 else v


# ─── Wire formats ever released ──────────────────────────────────────────────
HEADER_FIELDS = ("magic0", "magic1", "format", "block_words", "fw_version", "fw_build", "fw_flags", "tick_addr")

FORMATS = Formats([
    # Formats 1-3 predate the fixed header: recognised so `info` can name them, never read.
    FormatSpec(1, 0, legacy=True, note="before version reporting"),
    FormatSpec(2, 0, legacy=True, note="before version reporting"),
    FormatSpec(3, 0, legacy=True, note="before version reporting"),
    FormatSpec(4, 0, note="fixed 8-word header, sync, identity, temperature, battery, model id", adds=HEADER_FIELDS + (
        "seq", "ack_seq", "hold",
        "anchor_tick", "anchor_us_lo", "anchor_us_hi", "corr_ppb",
        "epoch_us_lo", "epoch_us_hi", "period_us",
        "uid0", "uid1", "uid2", "uid3",
        "temp_cdeg", "temp_min_cdeg", "temp_max_cdeg", "temp_sum_cdeg", "temp_n",
        "temp_raw", "vref_raw", "stats_tick",
        "batt_mv", "power_state", "wake_count",
        "model_id",
    )),
    # Next minor goes here, e.g.:  FormatSpec(4, 1, adds=("model_id",), note="board model word"),
])


# ─── Decoders ────────────────────────────────────────────────────────────────
def decode_temperature_v1(blk) -> dict | None:
    """Die temperature stats in degC, from the factory two-point calibration (firmware 0.4.0+)."""
    t = s32(blk.temp_cdeg)
    if t == NO_TEMP:
        return None
    n = blk.temp_n
    out = {"now_c": t / 100, "n": n, "raw": blk.temp_raw, "vref_raw": blk.vref_raw}
    if n:
        out.update(min_c=s32(blk.temp_min_cdeg) / 100, max_c=s32(blk.temp_max_cdeg) / 100,
                   mean_c=s32(blk.temp_sum_cdeg) / n / 100)
    return out


def decode_power_v1(blk) -> dict:
    return {"mv": blk.batt_mv or None, "low": bool(blk.power_state & 1),
            "usb": bool(blk.power_state & 2), "wakes": blk.wake_count}


def decode_identity_v1(blk) -> bytes:
    return b"".join(getattr(blk, f"uid{i}").to_bytes(4, "little") for i in range(4))


# ─── Features ────────────────────────────────────────────────────────────────
FIRST_FW = (0, 4, 0)       # the firmware that introduced format 4.0

FEATURES = [
    Feature("clock_sync", doc="read/write the anchor, rate correction and beat grid", variants=(
        Variant("v1", Fields("tick_addr", "seq", "ack_seq", "anchor_tick", "anchor_us_lo", "anchor_us_hi",
                             "corr_ppb", "epoch_us_lo", "epoch_us_hi", "period_us")),)),
    Feature("hold", doc="keep the unit in its boot guard", variants=(Variant("v1", Fields("hold")),)),
    Feature("identity", doc="chip UID", variants=(
        Variant("v1", Fields("uid0", "uid1", "uid2", "uid3"), decode_identity_v1),)),
    # A recomputed temperature would be added in FRONT as, say,
    #   Variant("v2", Fields(...) & Firmware(min=(0, 6, 0)), decode_temperature_v2),
    # and a board that lacks the sensor would get  NotModel("no-sensor-board")  on every variant.
    Feature("temperature", doc="die temperature since the last adopted sync", variants=(
        Variant("v1", Fields("temp_cdeg", "temp_min_cdeg", "temp_max_cdeg", "temp_sum_cdeg", "temp_n",
                             "temp_raw", "vref_raw") & Firmware(min=FIRST_FW), decode_temperature_v1),)),
    Feature("power", doc="battery voltage, low-battery latch, USB, wake count", variants=(
        Variant("v1", Fields("batt_mv", "power_state", "wake_count") & Firmware(min=FIRST_FW),
                decode_power_v1),)),
]

FEATURES.append(Feature("writable", doc="the connection can write to the unit (SWD can; a read-only link cannot)",
                        variants=(Variant("v1", Access("write")),), hardware=False))

# ─── Commands ────────────────────────────────────────────────────────────────
# `Access` is about the connection (can we write?), the rest about the unit. `optional` features
# degrade: the command runs and says what it could not record.
COMMANDS = {
    "info":    CommandNeeds(),
    "status":  CommandNeeds(required=("clock_sync",), optional=("identity", "temperature", "power")),
    "sync":    CommandNeeds(required=("clock_sync", "writable"), optional=("identity", "temperature", "power")),
    "resync":  CommandNeeds(required=("clock_sync", "writable"), optional=("identity", "temperature", "power")),
    "hold":    CommandNeeds(required=("hold", "writable")),
    "release": CommandNeeds(required=("hold", "writable")),
}


# ─── Transports ──────────────────────────────────────────────────────────────
# Add one per way of reaching a unit; `access` is what it allows. A model lists the transports it
# can be reached over (via traits), so a board without, say, a radio is refused a radio link.
TRANSPORTS = [
    Transport("swd", access=("read", "write")),
]

# ─── Models ──────────────────────────────────────────────────────────────────
# A model is an id (what the firmware reports in `model_id`, set with -DLB_MODEL_ID) plus traits.
# A trait is what the hardware can provide (feature names) and the transports that reach it.
CORE = Trait("core", capabilities=("clock_sync", "hold", "identity"), transports=("swd",))
DIE_TEMP = Trait("die-temp", capabilities=("temperature",))
BATTERY_SENSE = Trait("battery-sense", capabilities=("power",))

BUG = Model(0, "py32-bug", (CORE, DIE_TEMP, BATTERY_SENSE))
MODELS = [
    BUG,
    # A new board is one line, composed from what it shares with the others, e.g.
    #   BUG.derive(1, "py32-bug-lite", drop=("die-temp",)),                 # same, but no temperature
    #   BUG.derive(2, "py32-bug-radio", add=(Trait("radio", transports=("radio",)),)),   # + a radio link
    # A board that converts a reading differently gets a marker trait (Trait("temp-cal-b")) and the
    # feature gets a Variant requiring HasTrait("temp-cal-b") with its own decoder.
]
DEFAULT_MODEL = BUG.id             # what a format without a model word (or a model id of 0) means

CATALOG = Catalog(FORMATS, FEATURES, COMMANDS, MODELS, TRANSPORTS, default_model=DEFAULT_MODEL)
