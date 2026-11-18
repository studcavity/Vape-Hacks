"""tools/lb_stack.py: call-graph analysis (synthetic graphs, no toolchain) and, when arduino-cli and
the py32duino core are installed, the real firmware's worst-case stack against every model's budget."""
import shutil
import subprocess

import pytest

import lb_catalog
import lb_stack
from lb_compat import Model, Trait


def ci(*items):
    """A fake gcc .ci file: ('f', 24) is a node with a frame, ('f', 'g') an edge f -> g."""
    lines = ['graph: { title: "x.cpp"']
    for a, b in items:
        if isinstance(b, int):
            lines.append(f'node: {{ title: "{a}" label: "void {a}()\\nx.cpp:1:1\\n{b} bytes (static)" }}')
        else:
            lines.append(f'edge: {{ sourcename: "{a}" targetname: "{b}" }}')
    return "\n".join(lines) + "\n}"


def graph(*items):
    g = lb_stack.Graph()
    g.add_ci(ci(*items))
    return g


BASE = [("main", 8), ("loop", 40), ("deep", 100), ("shallow", 10), ("main", "loop"), ("loop", "deep"), ("loop", "shallow"),
        ("EXTI0_1_IRQHandler", 8), ("EXTI4_15_IRQHandler", 16), ("SysTick_Handler", 8), ("tick", 8),
        ("SysTick_Handler", "tick"), ("EXTI4_15_IRQHandler", "deep")]
GROUPS = {"exti": ("EXTI0_1_IRQHandler", "EXTI4_15_IRQHandler"), "systick": ("SysTick_Handler",)}


# ── analysis ─────────────────────────────────────────────────────────────────
def test_thread_depth_is_the_longest_chain_not_the_sum_of_branches():
    r = lb_stack.analyse(graph(*BASE), groups=GROUPS)
    assert r.thread.depth == 8 + 40 + 100
    assert r.thread.chain == ["void main()[8]", "void loop()[40]", "void deep()[100]"]


def test_interrupt_groups_add_up_but_members_of_a_group_do_not():
    r = lb_stack.analyse(graph(*BASE), groups=GROUPS)
    exti = 32 + (16 + 100) + 32          # the larger member only: they share a priority and cannot nest
    systick = 32 + (8 + 8) + 32
    assert r.interrupts["exti"][0] == exti and r.interrupts["systick"][0] == systick
    assert r.total == r.thread.depth + exti + systick


def test_a_listed_interrupt_that_is_not_in_the_build_is_an_error():
    with pytest.raises(lb_stack.StackError, match="NOPE_IRQHandler"):
        lb_stack.analyse(graph(*BASE), groups={"x": ("NOPE_IRQHandler",)})


def test_static_constructors_run_before_main_and_count_as_roots():
    g = graph(*BASE, ("_GLOBAL__sub_I_obj", 400))
    assert lb_stack.analyse(g, groups=GROUPS).thread.depth == 400


def test_unmeasured_callee_is_assumed_and_reported_and_elf_frames_replace_the_assumption():
    items = BASE + [("shallow", "libhelper")]
    r = lb_stack.analyse(graph(*items), groups=GROUPS)
    assert any("libhelper" in n and "assumed" in n for n in r.notes)
    r2 = lb_stack.analyse(graph(*items), {"libhelper": (500, set())}, groups=GROUPS)    # a big library frame
    assert r2.thread.depth == 8 + 40 + 10 + 500 and not any("libhelper" in n for n in r2.notes)


def test_elf_callees_are_followed_through_library_code():
    items = BASE + [("shallow", "lib_a")]
    elf = {"lib_a": (20, {"lib_b"}), "lib_b": (300, set())}
    assert lb_stack.analyse(graph(*items), elf, groups=GROUPS).thread.depth == 8 + 40 + 10 + 20 + 300


def test_recursion_is_flagged_not_looped_on():
    r = lb_stack.analyse(graph(*BASE, ("deep", "loop")), groups=GROUPS)
    assert any("recursion" in n for n in r.notes)


def test_dynamic_frames_are_flagged():
    g = lb_stack.Graph()
    g.add_ci(ci(*BASE).replace('100 bytes (static)', '100 bytes (dynamic)'))
    assert any("dynamic frame" in n for n in lb_stack.analyse(g, groups=GROUPS).notes)


def test_missing_call_graph_files_are_explained(tmp_path):
    with pytest.raises(lb_stack.StackError, match="fcallgraph-info"):
        lb_stack.Graph.from_dir(tmp_path)


def test_static_file_local_functions_are_found_by_their_bare_symbol():
    g = lb_stack.Graph()
    g.add_ci(ci(("main", 8), ("/b/s.cpp:_ZL4leaf", 50), ("main", "/b/s.cpp:_ZL4leaf")))
    assert g.find("_ZL4leaf") == ["/b/s.cpp:_ZL4leaf"]
    assert lb_stack.analyse(g, groups={}).thread.depth == 58


# ── budgets and model metadata ───────────────────────────────────────────────
def report(total):
    return lb_stack.Report(lb_stack.Result(total, []), {}, total, [])


def test_compare_flags_exceeding_the_model_budget_and_a_budget_larger_than_the_linker_reserve():
    m = Model(9, "m", (Trait("chip", ram_bytes=8192, max_stack_bytes=500),))
    assert lb_stack.compare(report(500), m) == []
    assert "exceeds its budget of 500 B" in lb_stack.compare(report(501), m)[0]
    assert "linker reserves" in lb_stack.compare(report(100), m, {"stack_min": 400})[0]
    assert lb_stack.compare(report(100), Model(9, "none", ()))[0].endswith("(add one via its chip trait)")


def test_model_limits_come_from_traits_and_the_tightest_one_wins():
    chip = Trait("chip", ram_bytes=8192, max_stack_bytes=768)
    tight = Trait("tight", max_stack_bytes=256)
    m = Model(1, "a", (chip,))
    assert (m.ram_bytes, m.max_stack_bytes) == (8192, 768)
    d = m.derive(2, "b", add=(tight,))
    assert d.max_stack_bytes == 256 and d.ram_bytes == 8192 and m.max_stack_bytes == 768
    small = Model(3, "small", (Trait("chip4k", ram_bytes=4096, max_stack_bytes=384),))
    assert small.ram_bytes == 4096


def test_every_catalog_model_declares_ram_and_a_stack_budget_within_it():
    for m in lb_catalog.MODELS:
        assert m.ram_bytes > 0 and 0 < m.max_stack_bytes < m.ram_bytes, m.name


# ── the real firmware (needs arduino-cli and the PY32 core; skipped otherwise) ─
def _toolchain():
    cli = shutil.which("arduino-cli")
    if not cli:
        return "arduino-cli not installed"
    cores = subprocess.run([cli, "core", "list"], capture_output=True, text=True).stdout
    return None if "PY32Duino:PY32" in cores else "PY32Duino core not installed"


@pytest.fixture(scope="session")
def stack_cache(tmp_path_factory):
    return tmp_path_factory.mktemp("lb_stack_cache")


@pytest.mark.toolchain
@pytest.mark.parametrize("model", lb_catalog.MODELS, ids=lambda m: m.name)
def test_real_firmware_fits_every_models_stack_budget(model, tmp_path, stack_cache):
    why = _toolchain()
    if why:
        pytest.skip(why)
    report_, problems = lb_stack.check_model(model, tmp_path, cache=stack_cache)
    assert problems == [], "\n".join(report_.lines() + problems)
    assert report_.thread.depth > 0 and set(report_.interrupts) == set(lb_stack.INTERRUPT_GROUPS)
