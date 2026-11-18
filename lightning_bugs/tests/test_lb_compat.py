"""lb_compat / lb_catalog: wire formats, firmware variants, models and per-command needs.

The generic machinery is exercised with a made-up catalog (formats 4.0-4.2, a temperature that was
recomputed in fw 0.6, a board without the sensor); the real catalog gets consistency checks."""
import pytest

import lb_catalog
from lb_compat import (Access, AnyOf, Catalog, CommandNeeds, Feature, Fields, Firmware, FormatSpec, Formats,
                       NotModel, OnModel, Unit, Unsupported, Variant, describe_header, parse_header)


def make_catalog():
    formats = Formats([
        FormatSpec(3, 0, legacy=True),
        FormatSpec(4, 0, adds=("magic0", "magic1", "format", "block_words", "fw_version", "fw_build", "fw_flags",
                               "tick_addr", "seq", "temp")),
        FormatSpec(4, 1, adds=("model_id",)),
        FormatSpec(4, 2, adds=("temp2", "hum")),
    ])
    temp = Feature("temperature", (
        Variant("v2", Fields("temp2") & Firmware(min=(0, 6, 0)) & NotModel("no-sensor"), "dec2"),
        Variant("v1", Fields("temp") & Firmware(min=(0, 4, 0), below=(0, 6, 0)) & NotModel("no-sensor"), "dec1"),
    ))
    humidity = Feature("humidity", (Variant("v1", Fields("hum") & OnModel("deluxe")),))
    sync = Feature("sync", (Variant("v1", Fields("seq")),))
    writable = Feature("writable", (Variant("v1", Access("write")),))

    def identify(layout, read):
        return {1: "deluxe", 2: "no-sensor"}.get(read("model_id"), "basic")
    cmds = {"stats": CommandNeeds(required=("sync",), optional=("temperature", "humidity")),
            "push": CommandNeeds(required=("sync", "writable")),
            "climate": CommandNeeds(required=("temperature", "humidity"))}
    return Catalog(formats, [temp, humidity, sync, writable], cmds, identify)


def words(cat, major=4, minor=0, fw=(0, 4, 0), n=None, **fields):
    layout = cat.formats.layout(major, minor)
    w = [0] * (n or layout.words)
    w[2] = major << 16 | minor
    w[3] = len(w)
    w[4] = fw[0] << 16 | fw[1] << 8 | fw[2]
    for k, v in fields.items():
        w[layout.index[k]] = v
    return w


# ── formats ──────────────────────────────────────────────────────────────────
def test_layouts_are_cumulative_and_old_minors_keep_their_own():
    f = make_catalog().formats
    assert f.layout(4, 0).words == 10 and f.layout(4, 1).fields[-1] == "model_id"
    assert f.layout(4, 2).fields[:10] == f.layout(4, 0).fields          # a prefix: minors only append
    assert f.layout(4, 9).minor == 2                                    # newer than known: known prefix
    assert f.layout(5, 0) is None and f.layout(3, 0) is None            # other major / legacy: unreadable
    assert f.is_legacy(3)


def test_format_registry_rejects_gaps_and_duplicates():
    with pytest.raises(ValueError, match="no 4.0"):
        Formats([FormatSpec(4, 1, adds=("a",))])
    with pytest.raises(ValueError, match="twice"):
        Formats([FormatSpec(4, 0, adds=("a",)), FormatSpec(4, 1, adds=("a",))])
    with pytest.raises(ValueError, match="listed twice"):
        Formats([FormatSpec(4, 0, adds=("a",)), FormatSpec(4, 0, adds=("b",))])


# ── firmware variants ────────────────────────────────────────────────────────
@pytest.mark.parametrize("fw, minor, expect", [
    ((0, 4, 0), 2, "v1"), ((0, 5, 9), 2, "v1"), ((0, 6, 0), 2, "v2"), ((1, 0, 0), 2, "v2"),
    ((0, 6, 0), 0, None),        # new firmware but the 4.0 layout has no temp2: no variant fits
    ((0, 3, 0), 2, None),        # too old for any
])
def test_firmware_picks_the_variant(fw, minor, expect):
    cat = make_catalog()
    st = cat.status(cat.unit_from_words(words(cat, minor=minor, fw=fw)), "temperature")
    assert st.variant == expect
    if expect is None:
        assert len(st.reasons) == 2 and all(r.startswith("v") for r in st.reasons)


def test_impl_is_returned_with_the_variant():
    cat = make_catalog()
    u = cat.unit_from_words(words(cat, minor=2, fw=(0, 7, 0)))
    assert cat.variant(u, "temperature").impl == "dec2"


# ── models ───────────────────────────────────────────────────────────────────
def test_model_is_read_from_the_block_and_gates_variants():
    cat = make_catalog()
    basic = cat.unit_from_words(words(cat, minor=2, fw=(0, 6, 0), model_id=0))
    sensorless = cat.unit_from_words(words(cat, minor=2, fw=(0, 6, 0), model_id=2))
    deluxe = cat.unit_from_words(words(cat, minor=2, fw=(0, 6, 0), model_id=1))
    assert [u.model for u in (basic, sensorless, deluxe)] == ["basic", "no-sensor", "deluxe"]
    assert cat.supports(basic, "temperature") and not cat.supports(sensorless, "temperature")
    assert cat.supports(deluxe, "humidity") and not cat.supports(basic, "humidity")
    assert "model 'basic' is not 'deluxe'" in cat.status(basic, "humidity").reasons[0]


def test_unit_without_a_model_word_gets_the_default_identification():
    cat = make_catalog()
    assert cat.unit_from_words(words(cat, minor=0)).model == "basic"      # 4.0 has no model_id


# ── commands ─────────────────────────────────────────────────────────────────
def test_command_reports_every_missing_required_feature_at_once():
    cat = make_catalog()
    u = cat.unit_from_words(words(cat, minor=0, fw=(0, 3, 0)))      # too old for temperature, no hum word
    with pytest.raises(Unsupported) as e:
        cat.check_command(u, "climate")
    msg = str(e.value)
    assert "temperature" in msg and "humidity" in msg
    assert "older than 0.4.0" in msg and "has no hum" in msg


def test_optional_features_degrade_instead_of_refusing():
    cat = make_catalog()
    u = cat.unit_from_words(words(cat, minor=0, fw=(0, 4, 0)))
    lacking = cat.check_command(u, "stats")
    assert [s.feature for s in lacking] == ["humidity"]               # temperature v1 is fine on 4.0/0.4.0


def test_access_gates_commands_independent_of_the_unit():
    cat = make_catalog()
    w = words(cat, minor=2, fw=(0, 6, 0))
    ro = cat.unit_from_words(w, access={"read"})
    rw = cat.unit_from_words(w, access={"read", "write"})
    cat.check_command(ro, "stats")                                     # reading needs no write
    with pytest.raises(Unsupported, match="cannot write"):
        cat.check_command(ro, "push")
    cat.check_command(rw, "push")


def test_a_bare_header_is_enough_to_identify_a_unit():
    cat = make_catalog()
    full = words(cat, minor=2, fw=(0, 6, 0))
    u = cat.unit_from_words(full[:8])                                  # header only: e.g. a short beacon packet
    assert (u.major, u.minor, u.fw) == (4, 2, (0, 6, 0)) and u.layout.minor == 2
    assert describe_header(parse_header(full[:8])) == "firmware 0.6.0 (build unknown), wire format 4.2"


def test_legacy_and_unknown_majors_have_no_layout():
    cat = make_catalog()
    legacy = cat.unit_from_words([0, 0, 3, 0x20000400, 0, 0, 0, 0])
    assert legacy.layout is None and not cat.supports(legacy, "sync")
    assert "cannot be read" in cat.status(legacy, "sync").reasons[0]


def test_catalog_rejects_commands_naming_unknown_features():
    with pytest.raises(ValueError, match="unknown feature"):
        Catalog(Formats([FormatSpec(4, 0, adds=("a",))]), [], {"x": CommandNeeds(required=("nope",))})


# ── requirement algebra ──────────────────────────────────────────────────────
def test_requirements_compose_and_describe_themselves():
    r = Fields("a") & Firmware(min=(0, 6, 0)) & NotModel("x")
    assert r.describe() == "fields a and firmware >= 0.6.0 and not model x"
    u = Unit(4, 0, (0, 5, 0), None, "x")
    assert len(r.unmet(u)) == 3
    any_ = AnyOf(OnModel("a"), OnModel("b"))
    assert any_.ok(Unit(4, 0, None, None, "b")) and not any_.ok(Unit(4, 0, None, None, "c"))
    assert (OnModel("a") | OnModel("b") | OnModel("c")).describe() == "(model a or model b or model c)"


def test_firmware_bounds_on_unknown_firmware():
    assert Firmware(min=(0, 1, 0)).unmet(Unit(4, 0, None, None)) == ["firmware version unknown"]


# ── the real catalog ─────────────────────────────────────────────────────────
def test_real_catalog_is_internally_consistent():
    cat = lb_catalog.CATALOG
    latest = cat.formats.layout(4, cat.formats.latest(4))
    for name in lb_catalog.HEADER_FIELDS:
        assert name in latest
    for f in cat.features.values():                                    # every Fields() names real words
        for v in f.variants:
            parts = getattr(v.requires, "parts", (v.requires,))
            for p in parts:
                if isinstance(p, Fields):
                    assert set(p.names) <= set(latest.fields), (f.name, p.names)
    assert set(cat.commands) >= {"info", "status", "sync", "resync", "hold", "release"}


def test_real_catalog_supports_every_command_on_current_firmware_over_swd():
    cat = lb_catalog.CATALOG
    layout = cat.formats.layout(4, 0)
    w = [0] * layout.words
    w[2], w[3], w[4] = 4 << 16, layout.words, 4 << 8
    u = cat.unit_from_words(w, access={"read", "write"})
    for name in cat.commands:
        assert cat.check_command(u, name) == []
