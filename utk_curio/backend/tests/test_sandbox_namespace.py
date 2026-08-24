"""What names can a node's Python code see, and what crosses between nodes?

Two contracts, both from #158, both previously untested:

1. **The pre-seeded namespace.** The legacy subprocess wrapper
   (``utk_curio/sandbox/python_wrapper.txt``) did
   ``from utk_curio.sandbox.util.parsers import *``, and ``parsers.py`` has no
   ``__all__``, so it leaked ``np``, ``shapely.wkt``, ``math``, ``datetime``,
   ``Path`` and ``duckdb`` into user scope. When execution moved in-process,
   ``_worker_init`` replaced that star-import with an explicit five-name import
   and silently dropped them. That is why users reported ``pandas`` working
   across nodes with no import while ``numpy`` and ``shapely`` did not:
   ``pd``/``gpd`` were pre-seeded, ``np``/``wkt`` were not.

   The list below is pinned deliberately. A future refactor that drops one of
   these should fail here rather than in a user's dataflow.

2. **Imports crossing node boundaries.** A node's own ``import`` used to be
   unreachable from anywhere else by construction: user code is sunk into
   ``def userCode(arg):``, so every import in it is function-local. Imports are
   now hoisted into a session-scoped namespace, so an upstream
   ``import numpy as np`` reaches downstream nodes.

   The consequences are tested in both directions on purpose: sharing is scoped
   to *imports* (never plain variables) and to *one session*, and it makes a node
   that leans on an upstream import order-dependent. Those are the properties a
   future change is most likely to break silently.

Runs ``execute_code`` directly - no Flask, no sandbox HTTP server, no browser.

Run::

    pytest utk_curio/backend/tests/test_sandbox_namespace.py -v
"""
from __future__ import annotations

import textwrap

import pytest

from utk_curio.sandbox.app import worker


@pytest.fixture(scope="module", autouse=True)
def _init_worker():
    """Build ``_globals_cache`` once, exactly as sandbox startup does."""
    worker._worker_init()


@pytest.fixture(autouse=True)
def _clear_session_imports():
    """Each test starts with no accumulated cross-node imports.

    Tolerant of the attribute being absent so a worker without cross-node
    imports fails on the specific assertion describing the missing contract,
    rather than erroring in setup for every test in the file.
    """
    store = getattr(worker, "_session_imports", None)
    if store is not None:
        store.clear()
    yield
    if store is not None:
        store.clear()


def run(body: str, session_id: str = "sess-1") -> dict:
    """Execute ``body`` as a node would.

    The frontend indents every line by four spaces before POSTing it (see
    ``PythonInterpreter.interpretCode``), so the code reaching ``execute_code``
    is always ready to drop into ``def userCode(arg):``. Reproducing that here
    matters: the import hoister has to dedent before it can parse, and a test
    that skipped the indent would not exercise that.
    """
    indented = "".join(
        "    " + line + "\n"
        for line in textwrap.dedent(body).strip("\n").split("\n")
    )
    return worker.execute_code(
        indented, "", "curio.builtin/computation-analysis", "str",
        session_id=session_id, save_dataset=False,
    )


def stdout_of(result: dict) -> str:
    assert not result["stderr"], result["stderr"]
    return "\n".join(result["stdout"])


# ---------------------------------------------------------------------------
# 1. The pre-seeded namespace
# ---------------------------------------------------------------------------

#: Every name the legacy star-import leaked, plus the ones that were always
#: explicit. Pinned so a dropped entry fails here, not in a user's dataflow.
EXPECTED_SEEDED_NAMES = {
    # always explicit
    "gpd", "pd", "json", "mmap", "zlib", "os", "time", "hashlib", "ast", "io",
    "warnings",
    # leaked by `from parsers import *` before the in-process move (#158)
    "np", "numpy", "shapely", "wkt", "math", "datetime", "Path", "duckdb",
    # sandbox helpers
    "load_from_duckdb", "save_to_duckdb", "detect_kind", "checkIOType",
    "save_dataset_parquet",
}


def test_seeded_globals_cover_every_legacy_name():
    missing = EXPECTED_SEEDED_NAMES - set(worker._globals_cache)
    assert not missing, (
        "names dropped from the sandbox's pre-seeded namespace: "
        + str(sorted(missing))
        + ". Nodes relying on them fail with NameError even though the library "
        "is installed - exactly the #158 regression."
    )


@pytest.mark.parametrize("expr,expected", [
    ("np.mean([1, 2, 3])", "2.0"),
    ("math.floor(2.7)", "2"),
    ("wkt.loads('POINT (1 2)').x", "1.0"),
    ("type(datetime.date(2020, 1, 1)).__name__", "date"),
    ("Path('a/b').name", "b"),
    ("pd.Series([1, 2]).sum()", "3"),
])
def test_seeded_names_usable_without_an_import_line(expr, expected):
    """A node body with no imports at all can still use these."""
    out = stdout_of(run("print(" + expr + ")\nreturn 1"))
    assert out.strip() == expected


# ---------------------------------------------------------------------------
# 2. Imports crossing node boundaries
# ---------------------------------------------------------------------------

def test_upstream_import_reaches_a_downstream_node():
    """The issue's own scenario: node A imports, node B uses it bare."""
    run("import inspect as probe_mod\nreturn 1", session_id="flow-a")
    out = stdout_of(run("print(probe_mod.__name__)\nreturn 1", session_id="flow-a"))
    assert out.strip() == "inspect"


def test_from_import_and_dotted_import_both_cross():
    run(
        "from collections import Counter\nimport xml.etree.ElementTree\nreturn 1",
        session_id="flow-b",
    )
    out = stdout_of(run(
        "print(Counter('aab')['a'], xml.etree.ElementTree.__name__)\nreturn 1",
        session_id="flow-b",
    ))
    assert out.strip() == "2 xml.etree.ElementTree"


def test_a_fresh_session_does_not_inherit_another_session_import():
    """Sharing is per-session, so concurrent users cannot see each other."""
    run("import inspect as probe_mod\nreturn 1", session_id="flow-c")
    result = run("print(probe_mod.__name__)\nreturn 1", session_id="flow-d")
    assert "NameError" in result["stderr"], result["stderr"]


def test_plain_variables_still_do_not_leak_between_nodes():
    """The narrow guarantee: imports cross, ordinary user state does not.

    Without this the change would turn every node's locals into shared global
    state, a far bigger behavioural change than #158 asked for.
    """
    run("leaked = 99\nreturn 1", session_id="flow-e")
    result = run("print(leaked)\nreturn 1", session_id="flow-e")
    assert "NameError" in result["stderr"], result["stderr"]


def test_a_node_run_before_its_upstream_still_fails():
    """The honest cost of cross-node imports: order now matters.

    Documented rather than hidden - if this ever starts passing, something is
    resolving imports process-globally instead of per-session and the isolation
    asserted above is no longer real.
    """
    result = run("print(probe_mod.__name__)\nreturn 1", session_id="flow-f")
    assert "NameError" in result["stderr"], result["stderr"]


def test_a_guarded_optional_import_does_not_break_the_node():
    """An import inside try/except is conditional by intent.

    The hoister only lifts *top-level* statements, so a guarded optional
    dependency must not be turned into a hard failure.
    """
    out = stdout_of(run(
        """
        try:
            import totally_missing_pkg
        except ImportError:
            pass
        print('guard ok')
        return 1
        """,
        session_id="flow-g",
    ))
    assert out.strip() == "guard ok"


def test_a_failing_top_level_import_still_raises_at_the_users_line():
    """Hoisting must not swallow a genuine ModuleNotFoundError."""
    result = run("import totally_missing_pkg\nreturn 1", session_id="flow-h")
    assert "totally_missing_pkg" in result["stderr"]
    assert "ModuleNotFoundError" in result["stderr"]


def test_session_namespaces_are_capped():
    """A long-lived sandbox must not accumulate namespaces without bound.

    There is no session-close signal in this process, so the LRU cap is the only
    thing bounding it.
    """
    cap = getattr(worker, "_MAX_IMPORT_SESSIONS", None)
    assert cap, "the sandbox no longer bounds its per-session import namespaces"
    for i in range(cap + 8):
        run("import inspect as probe_mod\nreturn 1", session_id="bulk-" + str(i))
    assert len(worker._session_imports) <= cap
