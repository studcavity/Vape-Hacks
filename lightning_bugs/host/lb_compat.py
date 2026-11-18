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


# ─── The unit being asked ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Unit:
    """Everything requirements can look at. Build one per attached device."""
    major: int
    minor: int
    fw: Version | None
    layout: Layout | None          # None: a format we cannot read
    model: str = "unknown"
    access: frozenset = frozenset({"read"})   # what the transport can do: "read", "write" (SWD has both)

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
        return [] if unit.model in self.names else [f"model {unit.model!r} is not {' or '.join(map(repr, self.names))}"]

    def describe(self):
        return "model " + " or ".join(self.names)


@dataclass(frozen=True, repr=False)
class NotModel(Requirement):
    names: tuple

    def __init__(self, *names: str):
        object.__setattr__(self, "names", tuple(names))

    def unmet(self, unit):
        return [f"not available on model {unit.model!r}"] if unit.model in self.names else []

    def describe(self):
        return "not model " + " or ".join(self.names)


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
    """Formats + features + commands (+ how to tell models apart), and the questions to ask them."""

    def __init__(self, formats: Formats, features: list[Feature], commands: dict[str, CommandNeeds],
                 identify_model: Callable[[Layout | None, Callable[[str], int | None]], str] | None = None):
        self.formats = formats
        self.features = {f.name: f for f in features}
        self.commands = commands
        self._identify = identify_model
        for c, needs in commands.items():
            for n in needs.required + needs.optional:
                if n not in self.features:
                    raise ValueError(f"command {c!r} needs unknown feature {n!r}")

    def unit(self, major: int, minor: int, fw: Version | None,
             read_field: Callable[[str], int | None] = lambda n: None,
             access: frozenset | set = frozenset({"read"})) -> Unit:
        layout = self.formats.layout(major, minor)
        model = self._identify(layout, read_field) if self._identify else "unknown"
        return Unit(major, minor, fw, layout, model, frozenset(access))

    def unit_from_words(self, words, access: frozenset | set = frozenset({"read"})) -> Unit:
        """Identify a unit from a block of words obtained any way at all (SWD, a log, a radio packet).
        `words` may be just the header, or the whole block (model detection reads the later fields)."""
        h = parse_header(words)
        if h.legacy:
            return Unit(h.major, 0, None, None, "unknown", frozenset(access))
        layout = self.formats.layout(h.major, h.minor)

        def read_field(name):
            return words[layout.index[name]] if layout and name in layout and layout.index[name] < len(words) else None
        return self.unit(h.major, h.minor, h.fw, read_field, access)

    def status(self, unit: Unit, feature: str) -> FeatureStatus:
        f = self.features[feature]
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
        missing = [s for s in (self.status(unit, n) for n in needs.required) if not s.ok]
        if missing:
            lines = [f"{s.feature} ({'; '.join(s.reasons)})" for s in missing]
            raise Unsupported(f"`{command}` needs " + ", ".join(lines), [r for s in missing for r in s.reasons])
        return [s for s in (self.status(unit, n) for n in needs.optional) if not s.ok]

    def report(self, unit: Unit) -> list[FeatureStatus]:
        return [self.status(unit, n) for n in self.features]
