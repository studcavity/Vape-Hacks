"""
lb_compat.py — what a unit's sync block can do, given its wire format, firmware and model.

Three independent facts describe a unit, and they change independently:

  wire format  which words exist and where (major.minor). Minors only append words, so a
               format is "its predecessor plus these fields".
  firmware     what the words *mean* (a temperature recomputed in fw 0.6 has the same field
               name and position as before, but different numbers).
  model        which hardware it is (a new board may compute or lack things).

A host command does not care about any of that; it cares about *features* ("temperature",
"clock_sync"). A Feature has one or more Variants, each guarded by a Requirement over those
three facts and carrying the code (or data) that handles that combination. For a given unit,
the first variant whose requirement holds is the one used; if none holds, the feature is
unsupported and the reasons say exactly what would satisfy it.

Requirements are small predicate objects combined with `&` and `|` (composition, not a class
hierarchy: format x firmware x model is a cross product, and mixins would need one class per
combination). They are data, so they can also print themselves ("firmware >= 0.6.0").

This module is generic and has no project data; lb_catalog.py holds the real formats,
features, models and per-command needs. Pure Python: no pyocd, no hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

Version = tuple  # (major, minor, patch)


def fmt_version(v: Version | None) -> str:
    return ".".join(str(n) for n in v) if v else "unknown"


class Unsupported(Exception):
    """A unit lacks something a command or feature needs. Carries every unmet reason."""

    def __init__(self, message: str, reasons: list[str] | None = None):
        super().__init__(message)
        self.reasons = reasons or []


# ─── The fixed header (identical in every format that has one) ───────────────
HEADER_WORDS = 8
MAGIC0 = 0x4C425359                      # 'LBSY'
MAGIC1 = MAGIC0 ^ 0xFFFFFFFF


@dataclass
class Header:
    """The fixed first words of a sync block, parsed; valid for any format, including ones we cannot speak."""
    addr: int
    legacy: bool            # a pre-header layout (formats 1-3): only the format number is known
    major: int
    minor: int
    block_words: int | None
    fw: tuple | None        # (major, minor, patch)
    build: int | None       # git commit prefix; 0 = unknown
    dirty: bool
    tick_addr: int


def parse_header(words, addr: int = 0) -> Header:
    """Words 0..7 of a block, from whatever transport delivered them. Formats 1-3 had a bare small
    integer in word 2 and the tick address in word 3."""
    if words[2] < 0x10000:
        return Header(addr, True, words[2], 0, None, None, None, False, words[3])
    f = words[4]
    return Header(addr, False, words[2] >> 16, words[2] & 0xFFFF, words[3],
                  (f >> 16 & 0xFF, f >> 8 & 0xFF, f & 0xFF), words[5], bool(words[6] & 1), words[7])


def describe_header(h: Header) -> str:
    if h.legacy:
        return f"wire format {h.major} (older than version reporting; firmware version unknown)"
    build = f"build {h.build:08x}{'+dirty' if h.dirty else ''}" if h.build else "build unknown"
    return f"firmware {fmt_version(h.fw)} ({build}), wire format {h.major}.{h.minor}"


# ─── Wire formats ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FormatSpec:
    """One released wire format. `adds` are the words this minor appends to the previous minor
    of the same major (or, for minor 0, the whole layout). `legacy` formats predate the fixed
    header: we can name them but never read them."""
    major: int
    minor: int
    adds: tuple = ()
    note: str = ""
    legacy: bool = False


@dataclass(frozen=True)
class Layout:
    """The ordered words of one known format; `minor` is the one these fields belong to."""
    major: int
    minor: int
    fields: tuple

    @property
    def words(self) -> int:
        return len(self.fields)

    @property
    def index(self) -> dict:
        return {name: i for i, name in enumerate(self.fields)}

    def __contains__(self, name: str) -> bool:
        return name in self.fields


class Formats:
    """Every wire format ever released, so old units can be recognised and read by their own layout."""

    def __init__(self, specs: list[FormatSpec]):
        self.specs = sorted(specs, key=lambda s: (s.major, s.minor))
        seen = set()
        for s in self.specs:
            if (s.major, s.minor) in seen:
                raise ValueError(f"wire format {s.major}.{s.minor} listed twice")
            seen.add((s.major, s.minor))
            if not s.legacy and s.minor > 0 and (s.major, s.minor - 1) not in seen:
                raise ValueError(f"wire format {s.major}.{s.minor} has no {s.major}.{s.minor - 1} to append to")
        dup = [n for l in {s.major for s in self.specs if not s.legacy} for n in self._dups(l)]
        if dup:
            raise ValueError(f"field(s) defined twice within one major: {sorted(set(dup))}")

    def _fields_upto(self, major: int, minor: int) -> list:
        out = []
        for s in self.specs:
            if s.major == major and s.minor <= minor and not s.legacy:
                out.extend(s.adds)
        return out

    def _dups(self, major: int) -> list:
        f = self._fields_upto(major, 1 << 30)
        return [n for n in f if f.count(n) > 1]

    def spec(self, major: int, minor: int) -> FormatSpec | None:
        return next((s for s in self.specs if (s.major, s.minor) == (major, minor)), None)

    def is_legacy(self, major: int) -> bool:
        return any(s.legacy and s.major == major for s in self.specs)

    def latest(self, major: int) -> int | None:
        minors = [s.minor for s in self.specs if s.major == major and not s.legacy]
        return max(minors) if minors else None

    def layout(self, major: int, minor: int) -> Layout | None:
        """The layout to read a unit of format major.minor with. A minor this table does not know
        yet (newer than any listed) is read with the newest listed minor: it is a strict prefix."""
        top = self.latest(major)
        if top is None:
            return None
        use = min(minor, top)
        return Layout(major, use, tuple(self._fields_upto(major, use)))

    def history(self) -> list[str]:
        out = []
        for s in self.specs:
            tag = "legacy, header-only" if s.legacy else f"+{len(s.adds)} word(s)" if s.minor else f"{len(s.adds)} words"
            out.append(f"{s.major}.{s.minor}  {tag}{'  ' + s.note if s.note else ''}")
        return out


# ─── Models and transports ───────────────────────────────────────────────────
@dataclass(frozen=True)
class Trait:
    """A reusable piece of what hardware can do. Models are built by listing traits, so "has a die
    temperature sensor" is written once and shared. A trait may also be a pure marker that variants
    test for ("temp-cal-b": this board converts its temperature reading differently)."""
    name: str
    capabilities: frozenset = frozenset()     # feature names the hardware can provide
    transports: frozenset = frozenset()       # ways of reaching a unit with this trait
    ram_bytes: int = 0                        # total RAM (0 = this trait says nothing)
    max_stack_bytes: int = 0                  # stack the firmware may use on this model (0 = unspecified)

    def __init__(self, name: str, capabilities=(), transports=(), ram_bytes: int = 0, max_stack_bytes: int = 0):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "capabilities", frozenset(capabilities))
        object.__setattr__(self, "transports", frozenset(transports))
        object.__setattr__(self, "ram_bytes", ram_bytes)
        object.__setattr__(self, "max_stack_bytes", max_stack_bytes)


@dataclass(frozen=True)
class Model:
    """A board, identified by the id its firmware reports. Everything else about it is data here."""
    id: int
    name: str
    traits: tuple = ()

    @property
    def capabilities(self) -> frozenset:
        return frozenset().union(*(t.capabilities for t in self.traits))

    @property
    def transports(self) -> frozenset:
        return frozenset().union(*(t.transports for t in self.traits))

    def _limit(self, attr: str) -> int:
        """The tightest value any trait declares (0 if none does): a model built from several
        traits can only rely on the smallest budget it was given."""
        vals = [getattr(t, attr) for t in self.traits if getattr(t, attr)]
        return min(vals) if vals else 0

    @property
    def ram_bytes(self) -> int:
        return self._limit("ram_bytes")

    @property
    def max_stack_bytes(self) -> int:
        return self._limit("max_stack_bytes")

    def has_trait(self, name: str) -> bool:
        return any(t.name == name for t in self.traits)

    def derive(self, id: int, name: str, add=(), drop=()) -> "Model":
        """A variant of this model: same traits, plus `add`, minus the traits named in `drop`."""
        keep = tuple(t for t in self.traits if t.name not in drop)
        return Model(id, name, keep + tuple(t for t in add if t not in keep))

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Transport:
    """A way of talking to a unit, and what it allows ("read", "write")."""
    name: str
    access: frozenset

    def __init__(self, name: str, access=()):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "access", frozenset(access))


# ─── The unit being asked ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Unit:
    """Everything requirements can look at. Build one per attached device."""
    major: int
    minor: int
    fw: Version | None
    layout: Layout | None          # None: a format we cannot read
    model: Model = Model(-1, "undetermined")
    transport: str | None = None   # how we reached it (a Transport name)
    access: frozenset = frozenset({"read"})   # what that transport allows: "read", "write"

    def has(self, name: str) -> bool:
        return self.layout is not None and name in self.layout


# ─── Requirements ────────────────────────────────────────────────────────────
class Requirement:
    """A predicate over a Unit. `unmet(unit)` returns the reasons it fails (empty list = satisfied)."""

    def unmet(self, unit: Unit) -> list[str]:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError

    def __and__(self, other: "Requirement") -> "Requirement":
        return AllOf(self, other)

    def __or__(self, other: "Requirement") -> "Requirement":
        return AnyOf(self, other)

    def ok(self, unit: Unit) -> bool:
        return not self.unmet(unit)

    def __repr__(self) -> str:
        return f"<{self.describe()}>"


@dataclass(frozen=True, repr=False)
class Always(Requirement):
    def unmet(self, unit):
        return []

    def describe(self):
        return "always"


@dataclass(frozen=True, repr=False)
class Fields(Requirement):
    """The unit's wire format carries these words."""
    names: tuple

    def __init__(self, *names: str):
        object.__setattr__(self, "names", tuple(names))

    def unmet(self, unit):
        if unit.layout is None:
            return [f"wire format {unit.major}.{unit.minor} cannot be read by this script"]
        gone = [n for n in self.names if n not in unit.layout]
        return [f"wire format {unit.major}.{unit.minor} has no {', '.join(gone)}"] if gone else []

    def describe(self):
        return "fields " + ", ".join(self.names)


@dataclass(frozen=True, repr=False)
class Firmware(Requirement):
    """min <= firmware < below (either bound optional). Use to gate on what a field *means*."""
    min: Version | None = None
    below: Version | None = None

    def unmet(self, unit):
        if unit.fw is None:
            return ["firmware version unknown"]
        if self.min is not None and unit.fw < self.min:
            return [f"firmware {fmt_version(unit.fw)} is older than {fmt_version(self.min)}"]
        if self.below is not None and unit.fw >= self.below:
            return [f"firmware {fmt_version(unit.fw)} is {fmt_version(self.below)} or newer"]
        return []

    def describe(self):
        lo = f">= {fmt_version(self.min)}" if self.min else ""
        hi = f"< {fmt_version(self.below)}" if self.below else ""
        return "firmware " + " and ".join(x for x in (lo, hi) if x)


@dataclass(frozen=True, repr=False)
class OnModel(Requirement):
    names: tuple

    def __init__(self, *names: str):
        object.__setattr__(self, "names", tuple(names))

    def unmet(self, unit):
        return [] if unit.model.name in self.names else [f"model {unit.model.name!r} is not {' or '.join(map(repr, self.names))}"]

    def describe(self):
        return "model " + " or ".join(self.names)


@dataclass(frozen=True, repr=False)
class NotModel(Requirement):
    names: tuple

    def __init__(self, *names: str):
        object.__setattr__(self, "names", tuple(names))

    def unmet(self, unit):
        return [f"not available on model {unit.model.name!r}"] if unit.model.name in self.names else []

    def describe(self):
        return "not model " + " or ".join(self.names)


@dataclass(frozen=True, repr=False)
class HasTrait(Requirement):
    """The unit's model carries this trait (preferred over naming models: a new board that shares
    the trait is picked up automatically)."""
    name: str

    def unmet(self, unit):
        return [] if unit.model.has_trait(self.name) else [f"model {unit.model.name!r} lacks trait {self.name!r}"]

    def describe(self):
        return f"trait {self.name}"


@dataclass(frozen=True, repr=False)
class Access(Requirement):
    """The way we reached the unit allows this (e.g. a read-only link can fetch stats but not sync)."""
    needs: tuple

    def __init__(self, *needs: str):
        object.__setattr__(self, "needs", tuple(needs))

    def unmet(self, unit):
        gone = [n for n in self.needs if n not in unit.access]
        return [f"this connection cannot {', '.join(gone)}"] if gone else []

    def describe(self):
        return "access " + "+".join(self.needs)


@dataclass(frozen=True, repr=False)
class AllOf(Requirement):
    parts: tuple

    def __init__(self, *parts: Requirement):
        flat = []
        for p in parts:
            flat.extend(p.parts if isinstance(p, AllOf) else [p])
        object.__setattr__(self, "parts", tuple(flat))

    def unmet(self, unit):
        return [r for p in self.parts for r in p.unmet(unit)]

    def describe(self):
        return " and ".join(p.describe() for p in self.parts)


@dataclass(frozen=True, repr=False)
class AnyOf(Requirement):
    parts: tuple

    def __init__(self, *parts: Requirement):
        flat = []
        for p in parts:
            flat.extend(p.parts if isinstance(p, AnyOf) else [p])
        object.__setattr__(self, "parts", tuple(flat))

    def unmet(self, unit):
        reasons = [p.unmet(unit) for p in self.parts]
        return [] if any(not r for r in reasons) else ["none of: " + "; ".join(" + ".join(r) for r in reasons)]

    def describe(self):
        return "(" + " or ".join(p.describe() for p in self.parts) + ")"


# ─── Features, variants, commands ────────────────────────────────────────────
@dataclass(frozen=True)
class Variant:
    """One way to handle a feature, valid when `requires` holds. `impl` is whatever the caller
    needs to act on it (usually a decoder function); this module never looks inside it."""
    name: str
    requires: Requirement
    impl: Any = None


@dataclass(frozen=True)
class Feature:
    """Variants are tried in order; list the newest first, so a unit that satisfies several gets
    the most specific handling and an older unit falls through to the older one."""
    name: str
    variants: tuple
    doc: str = ""
    hardware: bool = True      # the unit's model must list it among its capabilities; False for
                               # things about the connection or format rather than the board


@dataclass(frozen=True)
class CommandNeeds:
    """`required` features must be supported or the command is refused. `optional` features
    degrade: the command runs and the report says what it could not record."""
    required: tuple = ()
    optional: tuple = ()


@dataclass
class FeatureStatus:
    feature: str
    variant: str | None            # None = unsupported
    reasons: list = field(default_factory=list)   # why not (per variant), when unsupported

    @property
    def ok(self) -> bool:
        return self.variant is not None


class Catalog:
    """Formats + features + commands + models + transports, and the questions to ask them."""

    def __init__(self, formats: Formats, features: list[Feature], commands: dict[str, CommandNeeds],
                 models: list[Model] = (), transports: list[Transport] = (), default_model: int = 0,
                 model_field: str = "model_id"):
        self.formats = formats
        self.features = {f.name: f for f in features}
        self.commands = commands
        self.models = {m.id: m for m in models}
        if len(self.models) != len(list(models)):
            raise ValueError("two models share an id")
        self.transports = {t.name: t for t in transports}
        self.default_model = default_model
        self.model_field = model_field
        if self.models and default_model not in self.models:
            raise ValueError(f"default model id {default_model} is not a listed model")
        for m in models:
            for t in m.transports:
                if t not in self.transports:
                    raise ValueError(f"model {m.name!r} uses unknown transport {t!r}")
        for c, needs in commands.items():
            for n in needs.required + needs.optional:
                if n not in self.features:
                    raise ValueError(f"command {c!r} needs unknown feature {n!r}")

    def model_for(self, layout: Layout | None, read_field: Callable[[str], int | None]) -> Model:
        """The model a unit reports. A format without the model word is the default model; a block
        we only have the header of cannot say; an id we have never heard of is its own, empty model
        (so commands are refused with a clear reason rather than guessing what the board can do)."""
        if not self.models:
            return Model(-1, "unknown")
        if layout is None or self.model_field not in layout:
            return self.models[self.default_model]
        mid = read_field(self.model_field)
        if mid is None:
            return Model(-1, "undetermined")
        return self.models.get(mid) or Model(mid, f"unknown(id {mid})")

    def unit(self, major: int, minor: int, fw: Version | None,
             read_field: Callable[[str], int | None] = lambda n: None,
             transport: str = "swd") -> Unit:
        if transport not in self.transports and self.transports:
            raise ValueError(f"unknown transport {transport!r}")
        t = self.transports.get(transport)
        layout = self.formats.layout(major, minor)
        return Unit(major, minor, fw, layout, self.model_for(layout, read_field), transport,
                    t.access if t else frozenset({"read"}))

    def unit_from_words(self, words, transport: str = "swd") -> Unit:
        """Identify a unit from a block of words obtained any way at all (SWD, a log, a radio packet).
        `words` may be just the header, or the whole block (the model word and any later field are
        only available from the whole block)."""
        h = parse_header(words)
        if h.legacy:
            return Unit(h.major, 0, None, None, Model(-1, "unknown"), transport,
                        self.transports[transport].access if transport in self.transports else frozenset())
        layout = self.formats.layout(h.major, h.minor)

        def read_field(name):
            return words[layout.index[name]] if layout and name in layout and layout.index[name] < len(words) else None
        return self.unit(h.major, h.minor, h.fw, read_field, transport)

    def status(self, unit: Unit, feature: str) -> FeatureStatus:
        f = self.features[feature]
        if unit.layout is None:
            return FeatureStatus(feature, None, [f"wire format {unit.major}.{unit.minor} cannot be read by this script"])
        if f.hardware and self.models and feature not in unit.model.capabilities:
            return FeatureStatus(feature, None, [f"model {unit.model.name!r} has no {feature}"])
        why = []
        for v in f.variants:
            r = v.requires.unmet(unit)
            if not r:
                return FeatureStatus(feature, v.name)
            why.append(f"{v.name}: " + "; ".join(r))
        return FeatureStatus(feature, None, why)

    def variant(self, unit: Unit, feature: str) -> Variant | None:
        st = self.status(unit, feature)
        return next((v for v in self.features[feature].variants if v.name == st.variant), None)

    def supports(self, unit: Unit, feature: str) -> bool:
        return self.status(unit, feature).ok

    def check_command(self, unit: Unit, command: str) -> list[FeatureStatus]:
        """Statuses of the command's optional features; raises Unsupported listing every required
        feature that is missing (not just the first)."""
        needs = self.commands[command]
        if unit.transport and self.models and unit.transport not in unit.model.transports:
            raise Unsupported(f"`{command}`: model {unit.model.name!r} cannot be reached over {unit.transport}",
                              [f"model {unit.model.name!r} is reached over: "
                               + (", ".join(sorted(unit.model.transports)) or "nothing known")])
        missing = [s for s in (self.status(unit, n) for n in needs.required) if not s.ok]
        if missing:
            lines = [f"{s.feature} ({'; '.join(s.reasons)})" for s in missing]
            raise Unsupported(f"`{command}` needs " + ", ".join(lines), [r for s in missing for r in s.reasons])
        return [s for s in (self.status(unit, n) for n in needs.optional) if not s.ok]

    def report(self, unit: Unit) -> list[FeatureStatus]:
        return [self.status(unit, n) for n in self.features]
