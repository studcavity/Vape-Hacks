#!/usr/bin/env python3
"""
lb_stack.py — worst-case stack depth of the firmware, checked against each model's stack budget.

    python3 tools/lb_stack.py                 # build for the first model, report, compare
    python3 tools/lb_stack.py --model NAME    # another model in host/lb_catalog.py
    python3 tools/lb_stack.py --all           # every model (exit 1 if any exceeds its budget)

How the number is made
  1. The firmware is compiled (into a scratch directory, never build/) with
     -fstack-usage -fcallgraph-info=su, so gcc writes each function's frame size and who it calls.
  2. The longest call chain from main() (and from the static constructors that run before it) is
     the thread-mode depth. Functions that were not compiled from source here (libgcc divide, libc
     memset, assembly) have no frame data; their frames are read from the linked ELF's
     disassembly (every push and `sub sp` summed: an upper bound), following their calls too.
  3. Interrupts can arrive at the deepest point. Each interrupt *group* (handlers sharing one
     NVIC priority cannot nest each other) adds the hardware exception frame (32 B), its longest
     handler chain, and an allowance for the callbacks reached through function pointers.
  total = thread depth + sum over groups of (32 + chain + callback allowance)
  4. total must not exceed the model's `max_stack_bytes` (host/lb_catalog.py), and that budget must
     not exceed the stack the linker reserves in the build (_Min_Stack_Size).

What it is not: a measurement of a running unit. It is a static upper bound over the calls the
compiler can see; indirect calls are covered only by the allowance below, recursion is flagged,
and the interrupt list (INTERRUPT_GROUPS) is a statement about the firmware that a test pins.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH_DIR = ROOT / "firmware" / "lightning_bugs"
sys.path.insert(0, str(ROOT / "host"))
import lb_catalog  # noqa: E402

DEFAULT_FQBN = "PY32Duino:PY32:GenF030:pnum=PY32F030x8"
EXC_FRAME_BYTES = 32            # Cortex-M0+ pushes r0-r3, r12, lr, pc, xPSR on exception entry
CALLBACK_ALLOWANCE_BYTES = 32   # std::function invoker + the user callback behind an interrupt handler
UNKNOWN_FRAME_BYTES = 32        # a callee with neither source nor disassembly: assumed, and reported

# Interrupts the firmware enables, grouped by NVIC priority: members of a group cannot nest each
# other, groups can. If the sketch starts using another interrupt, add it here (the test for the real
# build fails when a listed handler does not exist, not when an unlisted one appears: review this
# list whenever lightning_bugs.ino or lb_sync.h gains an attachInterrupt / peripheral interrupt).
INTERRUPT_GROUPS = {
    "exti (switch and USB wake)": ("EXTI0_1_IRQHandler", "EXTI2_3_IRQHandler", "EXTI4_15_IRQHandler"),
    "systick": ("SysTick_Handler",),
}


class StackError(Exception):
    pass


# ─── Reading gcc's call-graph output ─────────────────────────────────────────
_NODE = re.compile(r'node: \{ title: "([^"]+)" label: "([^"]*)"')
_EDGE = re.compile(r'edge: \{ sourcename: "([^"]+)" targetname: "([^"]+)"')
_SIZE = re.compile(r"(\d+) bytes \((static|dynamic|dynamic,bounded)\)")


@dataclass
class Graph:
    frame: dict = field(default_factory=dict)       # node -> own frame bytes (from gcc)
    calls: dict = field(default_factory=dict)       # node -> set of callees
    label: dict = field(default_factory=dict)       # node -> readable name
    dynamic: set = field(default_factory=set)       # nodes with alloca / VLAs (frame is a lower bound)

    def add_ci(self, text: str) -> None:
        for line in text.splitlines():
            m = _NODE.match(line)
            if m:
                title, label = m.groups()
                self.label.setdefault(title, label.split("\\n")[0])
                s = _SIZE.search(label)
                if s:
                    self.frame[title] = int(s.group(1))
                    if s.group(2) != "static":
                        self.dynamic.add(title)
                continue
            m = _EDGE.match(line)
            if m:
                self.calls.setdefault(m.group(1), set()).add(m.group(2))

    @classmethod
    def from_dir(cls, build_dir: Path) -> "Graph":
        g = cls()
        files = sorted(Path(build_dir).rglob("*.ci"))
        if not files:
            raise StackError(f"no .ci call-graph files under {build_dir}: was it built with -fcallgraph-info=su?")
        for f in files:
            g.add_ci(f.read_text(errors="replace"))
        return g

    def name(self, node: str) -> str:
        return self.label.get(node) or node.rsplit(":", 1)[-1]

    def find(self, symbol: str) -> list:
        """Nodes for a symbol: global ones are titled by name, file-local ones by 'path:name'."""
        return [t for t in set(self.frame) | set(self.calls) | set(self.label)
                if t == symbol or t.endswith(":" + symbol)]


# ─── Frames for code gcc did not compile here: read from the ELF ─────────────
_FUNC = re.compile(r"^([0-9a-f]+) <([^>]+)>:$")
_PUSH = re.compile(r"\bpush\s+\{([^}]*)\}")
_SUB_SP = re.compile(r"\bsub\s+sp,\s*(?:sp,\s*)?#(\d+)")
_BRANCH = re.compile(r"\b(?:bl|b|b\.n|b\.w|bl\.w)\s+[0-9a-f]+ <([^>+]+)>")


def find_tool(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    # Wherever arduino-cli keeps its data: the env override, the default, and setup.sh's in-repo copy.
    bases = [os.environ.get("ARDUINO_DIRECTORIES_DATA"), "~/.arduino15", str(ROOT / ".tools" / "arduino15")]
    for base in filter(None, bases):
        hits = sorted(glob.glob(os.path.join(os.path.expanduser(base), f"packages/*/tools/*/*/bin/{name}")))
        if hits:
            return hits[-1]
    return None


def elf_functions(elf: Path) -> dict:
    """symbol -> (frame bytes, callees) from the disassembly: every push (4 B per register) and
    `sub sp` in the body summed, so branches that push on different paths over-count (safe).
    objdump labels a function under one name only, so every alias (nm) is mapped to the same body."""
    objdump, nm = find_tool("arm-none-eabi-objdump"), find_tool("arm-none-eabi-nm")
    if not objdump or not nm:
        return {}
    out = subprocess.run([objdump, "-d", str(elf)], capture_output=True, text=True, check=True).stdout
    bodies, cur = {}, None                       # label -> [frame, callees]
    for line in out.splitlines():
        m = _FUNC.match(line)
        if m:
            cur = m.group(1)
            bodies[cur] = [0, set(), m.group(2)]
            continue
        if cur is None or "\t" not in line:
            continue
        ins = line.split("\t", 2)[-1]
        p = _PUSH.search(ins)
        if p:
            bodies[cur][0] += 4 * len([r for r in p.group(1).split(",") if r.strip()])
        s = _SUB_SP.search(ins)
        if s:
            bodies[cur][0] += int(s.group(1))
        b = _BRANCH.search(ins)
        if b and b.group(1) != bodies[cur][2]:
            bodies[cur][1].add(b.group(1))
    by_addr = {}
    for line in subprocess.run([nm, str(elf)], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in "TtWw":
            by_addr.setdefault(parts[0], []).append(parts[2])
    funcs = {}
    for addr, (frame, callees, label) in bodies.items():
        for name in by_addr.get(addr, [label]) + [label]:
            funcs[name] = (frame, callees)
    # gcc's call graph names C++ externals by signature; fall back to the bare demangled name
    # (the larger body wins if an overloaded name is ambiguous: safe).
    for line in subprocess.run([nm, "-C", str(elf)], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] in "TtWw" and parts[0] in bodies:
            bare = parts[2].split("(")[0].split()[-1]
            frame, callees, _ = bodies[parts[0]]
            old = funcs.get("bare:" + bare)
            funcs["bare:" + bare] = (max(frame, old[0]), callees | old[1]) if old else (frame, callees)
    return funcs


# ─── Depth ───────────────────────────────────────────────────────────────────
@dataclass
class Result:
    depth: int
    chain: list


class Analyzer:
    def __init__(self, graph: Graph, elf: dict | None = None):
        self.g = graph
        self.elf = elf or {}
        self.memo: dict = {}
        self.active: set = set()
        self.notes: set = set()          # things that make the number less than airtight

    def _frame_and_callees(self, node: str):
        g = self.g
        if g.label.get(node) == "Indirect Call Placeholder" or node == "Indirect Call Placeholder":      # gcc's marker for a call through a pointer: the
            return 0, set()                          # allowance per interrupt group stands in for it
        if node in g.frame:
            if node in g.dynamic:
                self.notes.add(f"dynamic frame (alloca/VLA): {g.name(node)}")
            return g.frame[node], set(g.calls.get(node, ()))
        sym = node.rsplit(":", 1)[-1]
        bare = (g.label.get(node) or sym).split("(")[0].split()[-1] if (g.label.get(node) or sym) else sym
        hit = self.elf.get(sym) or self.elf.get("bare:" + bare)
        if hit:
            frame, callees = hit
            return frame, set(callees) | set(g.calls.get(node, ()))
        self.notes.add(f"no frame data, assumed {UNKNOWN_FRAME_BYTES} B: {g.name(node)}")
        return UNKNOWN_FRAME_BYTES, set(g.calls.get(node, ()))

    def depth(self, node: str) -> Result:
        if node in self.memo:
            return self.memo[node]
        if node in self.active:
            self.notes.add(f"recursion through {self.g.name(node)} (counted once)")
            return Result(0, [])
        self.active.add(node)
        frame, callees = self._frame_and_callees(node)
        best = Result(0, [])
        for c in sorted(callees):
            r = self.depth(self._resolve(c))
            if r.depth > best.depth:
                best = r
        self.active.discard(node)
        res = Result(frame + best.depth, [f"{self.g.name(node)}[{frame}]"] + best.chain)
        self.memo[node] = res
        return res

    def _resolve(self, node: str) -> str:
        """An ELF-derived callee is a bare symbol; prefer the gcc node that carries a frame."""
        if node in self.g.frame or node in self.g.calls:
            return node
        hits = [t for t in self.g.frame if t.endswith(":" + node)]
        return hits[0] if len(hits) == 1 else node


@dataclass
class Report:
    thread: Result
    interrupts: dict                 # group -> (bytes including exception frame + allowance, chain)
    total: int
    notes: list
    static_ram: dict | None = None   # section sizes and linker reserves, printed with the report

    def lines(self) -> list:
        out = [f"thread mode: {self.thread.depth} B", "   " + " -> ".join(self.thread.chain)]
        for grp, (b, chain) in self.interrupts.items():
            out.append(f"interrupt group {grp}: {b} B = {EXC_FRAME_BYTES} exception frame + "
                       f"{b - EXC_FRAME_BYTES - CALLBACK_ALLOWANCE_BYTES} chain + {CALLBACK_ALLOWANCE_BYTES} callbacks")
            out.append("   " + " -> ".join(chain))
        out.append(f"worst case total: {self.total} B")
        out += [f"note: {n}" for n in self.notes]
        if self.static_ram:
            r = self.static_ram
            out.append(f"static RAM: .data {r['data']} + .bss {r['bss']} + .noinit {r['noinit']} "
                       f"= {r['static']} B; linker reserves heap {r['heap_min']} + stack {r['stack_min']}")
        return out


def analyse(graph: Graph, elf: dict | None = None, groups: dict | None = None) -> Report:
    an = Analyzer(graph, elf)
    roots = graph.find("main")
    if not roots:
        raise StackError("no main() in the call graph")
    inits = [t for t in set(graph.frame) | set(graph.calls) if "_GLOBAL__sub_I_" in t]
    thread = max((an.depth(t) for t in roots + inits), key=lambda r: r.depth)

    interrupts = {}
    for grp, handlers in (groups if groups is not None else INTERRUPT_GROUPS).items():
        best = None
        for h in handlers:
            nodes = graph.find(h)
            if not nodes:
                raise StackError(f"interrupt handler {h} (group {grp!r}) is not in the build: "
                                 "update INTERRUPT_GROUPS in tools/lb_stack.py")
            for n in nodes:
                r = an.depth(n)
                if best is None or r.depth > best.depth:
                    best = r
        interrupts[grp] = (EXC_FRAME_BYTES + best.depth + CALLBACK_ALLOWANCE_BYTES, best.chain)
    total = thread.depth + sum(b for b, _ in interrupts.values())
    return Report(thread, interrupts, total, sorted(an.notes))


# ─── Building and reading the ELF ────────────────────────────────────────────
def build(model, work: Path, fqbn: str = DEFAULT_FQBN, cache: Path | None = None) -> Path:
    """Compile the sketch for `model` into `work` with call-graph output; returns the ELF path."""
    cli = shutil.which("arduino-cli")
    if not cli:
        raise StackError("arduino-cli not found")
    flags = f"-fstack-usage -fcallgraph-info=su -DLB_MODEL_ID={model.id}u"
    cmd = [cli, "compile", "--fqbn", fqbn, "--build-path", str(work / "b"),
           # A fresh core cache: a cached core was built without the flags and would have no call graph.
           "--build-cache-path", str(cache or work / "cache"),
           "--output-dir", str(work / "out"),
           "--build-property", f"compiler.c.extra_flags={flags}",
           "--build-property", f"compiler.cpp.extra_flags={flags}", str(SKETCH_DIR)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise StackError("build failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    return work / "out" / "lightning_bugs.ino.elf"


def linker_reserves(elf: Path) -> dict:
    """_Min_Stack_Size / _Min_Heap_Size (absolute symbols) and section sizes, from the ELF."""
    nm, size = find_tool("arm-none-eabi-nm"), find_tool("arm-none-eabi-size")
    if not nm or not size:
        raise StackError("arm-none-eabi-nm/size not found")
    syms = {}
    for line in subprocess.run([nm, str(elf)], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in ("_Min_Stack_Size", "_Min_Heap_Size"):
            syms[parts[2]] = int(parts[0], 16)
    sec = {}
    for line in subprocess.run([size, "-A", str(elf)], capture_output=True, text=True, check=True).stdout.splitlines():
        p = line.split()
        if len(p) >= 2 and p[0] in (".data", ".bss", ".noinit"):
            sec[p[0][1:]] = int(p[1])
    return {"stack_min": syms.get("_Min_Stack_Size", 0), "heap_min": syms.get("_Min_Heap_Size", 0),
            "data": sec.get("data", 0), "bss": sec.get("bss", 0), "noinit": sec.get("noinit", 0),
            "static": sum(sec.get(k, 0) for k in ("data", "bss", "noinit"))}


def compare(report: Report, model, reserves: dict | None = None) -> list:
    """Budget violations for `model` (empty list = fits). `reserves` is linker_reserves() output."""
    if not model.max_stack_bytes:
        return [f"model {model.name!r} declares no max_stack_bytes (add one via its chip trait)"]
    problems = []
    if report.total > model.max_stack_bytes:
        problems.append(f"{model.name}: worst-case stack {report.total} B exceeds its budget of "
                        f"{model.max_stack_bytes} B")
    if reserves and reserves["stack_min"] and model.max_stack_bytes > reserves["stack_min"]:
        problems.append(f"{model.name}: stack budget {model.max_stack_bytes} B is more than the "
                        f"{reserves['stack_min']} B the linker reserves, so statics could crowd it out")
    return problems


def check_model(model, work: Path, cache: Path | None = None) -> tuple[Report, list]:
    """Build for `model`, analyse, and return (report, problems)."""
    elf = build(model, work, cache=cache)
    report = analyse(Graph.from_dir(work / "b"), elf_functions(elf))
    report.static_ram = linker_reserves(elf)
    return report, compare(report, model, report.static_ram)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=lb_catalog.MODELS[0].name, choices=[m.name for m in lb_catalog.MODELS])
    ap.add_argument("--all", action="store_true", help="check every model")
    ap.add_argument("--work", help="scratch directory to build in (default: a temporary one)")
    args = ap.parse_args(argv)
    models = list(lb_catalog.MODELS) if args.all else [m for m in lb_catalog.MODELS if m.name == args.model]
    failed = False
    with tempfile.TemporaryDirectory(prefix="lb_stack_") as tmp:
        base = Path(args.work or tmp)
        for m in models:
            print(f"== {m.name}: stack budget {m.max_stack_bytes} B")
            try:
                report, problems = check_model(m, base / m.name, cache=base / "cache")
            except StackError as e:
                print(f"error: {e}")
                return 1
            if report:
                print("\n".join(report.lines()))
            for p in problems:
                print("FAIL: " + p)
            failed |= bool(problems)
            if not problems:
                print(f"ok: {report.total} B of {m.max_stack_bytes} B")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
