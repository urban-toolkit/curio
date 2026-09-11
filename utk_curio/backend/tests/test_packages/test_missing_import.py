"""Which library a node's traceback says it was missing (#299).

Three claims, in descending order of how easy they are to get wrong:

1. **It reads the terminating line, not the whole text.** A chained traceback
   can carry a ``No module named`` for an optional dependency some library
   caught and re-raised; installing that one would answer a question nobody
   asked.
2. **It refuses everything pip cannot fix.** stdlib, Curio's own modules, a
   distribution that is already installed, and - the security half - anything
   whose "module name" is not a module name at all. The capture is ``[^']+``,
   and node code can raise ``ModuleNotFoundError`` with whatever ``name`` it
   likes, so this is a wider input than any manifest.
3. **It shares one alias table with the manifest scanner.** ``sklearn`` must
   resolve to ``scikit-learn`` in both places or a package built from a node's
   imports would declare a dependency the install button cannot install.
"""
from __future__ import annotations

import sys

import pytest

from utk_curio.backend.app.packages import dependency_scanner, pip_runner
from utk_curio.backend.app.packages.missing_import import detect


def _traceback(last_line: str, *, preamble: str = "") -> str:
    """A traceback whose terminating line is *last_line*."""
    head = preamble or (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 2, in userCode\n'
    )
    return head + last_line + "\n"


# ── 1. Detection ────────────────────────────────────────────────────────────


def test_names_the_module_and_its_distribution():
    found = detect(_traceback("ModuleNotFoundError: No module named 'sklearn'"))
    assert found["module"] == "sklearn"
    assert found["distribution"] == "scikit-learn"
    assert found["installable"] is True
    assert found["reason"] is None


def test_reduces_a_submodule_to_the_root_that_installs_it():
    # CPython reports the first absent segment and appends a suffix; the fix is
    # always the distribution providing the root, and the suffix must not
    # defeat the match.
    found = detect(_traceback(
        "ModuleNotFoundError: No module named 'sklearn.linear_model'; "
        "'sklearn' is not a package"
    ))
    assert found["module"] == "sklearn"
    assert found["distribution"] == "scikit-learn"


def test_reads_a_qualified_exception_name():
    found = detect(_traceback(
        "builtins.ModuleNotFoundError: No module named 'seaborn'"
    ))
    assert found["module"] == "seaborn"


def test_reads_a_real_traceback_from_the_sandbox_worker():
    # Built by running the thing rather than by hand, so a change in how the
    # sandbox formats a failure breaks this test instead of a user's install
    # button.
    import traceback

    try:
        exec("import curio_e2e_definitely_absent_pkg", {})
    except ModuleNotFoundError:
        text = traceback.format_exc()
    else:  # pragma: no cover
        pytest.fail("the premise is gone: that module is importable")

    found = detect(text)
    assert found["module"] == "curio_e2e_definitely_absent_pkg"
    assert found["installable"] is True


# ── 2. Non-detection ────────────────────────────────────────────────────────


@pytest.mark.parametrize("last_line", [
    "ImportError: cannot import name 'foo' from 'bar'",
    "ImportError: DLL load failed while importing _ssl",
    "ValueError: not a number",
    "NameError: name 'arg' is not defined",
])
def test_ignores_failures_an_install_would_not_fix(last_line):
    assert detect(_traceback(last_line)) is None


@pytest.mark.parametrize("stderr", [None, "", "   \n\n"])
def test_ignores_empty_output(stderr):
    assert detect(stderr) is None


def test_ignores_a_missing_module_that_is_not_the_terminating_failure():
    # The anchoring case. A library caught its own optional-dependency
    # ModuleNotFoundError and raised something else; the run failed for the
    # SECOND reason, and offering to install the first would be wrong.
    chained = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 3, in <module>\n'
        "ModuleNotFoundError: No module named 'optional_extra'\n"
        "\n"
        "During handling of the above exception, another exception occurred:\n"
        "\n"
        "Traceback (most recent call last):\n"
        '  File "<string>", line 2, in userCode\n'
        "RuntimeError: the backend is not configured\n"
    )
    assert detect(chained) is None


# ── 3. Refusals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("module", ["json", "os", "sys", "itertools"])
def test_refuses_stdlib(module):
    found = detect(_traceback(f"ModuleNotFoundError: No module named '{module}'"))
    assert found["installable"] is False
    assert found["reason"] == "stdlib"
    assert found["distribution"] is None


@pytest.mark.parametrize("module", sorted(dependency_scanner._CURIO_PROVIDED))
def test_refuses_what_curio_itself_provides(module):
    found = detect(_traceback(f"ModuleNotFoundError: No module named '{module}'"))
    assert found["installable"] is False
    assert found["reason"] == "curio-provided"


@pytest.mark.parametrize("injected", [
    "requests --index-url http://elsewhere/simple",
    "https://host/evil.tar.gz",
    "../../etc/passwd",
    "pkg; rm -rf /",
    "-r requirements.txt",
])
def test_refuses_a_name_that_is_not_a_distribution_name(injected):
    # Node code chooses this string. It must never reach pip's argv, and the
    # refusal has to happen here rather than being left to the route.
    found = detect(_traceback(
        f"ModuleNotFoundError: No module named '{injected}'"
    ))
    assert found["installable"] is False
    assert found["reason"] == "unsafe-name"
    assert found["distribution"] is None
    # And the same string would have been refused downstream anyway.
    with pytest.raises(pip_runner.PipSpecError):
        pip_runner.validate_python_requirement(injected)


def test_refuses_a_module_something_installed_already_provides(monkeypatch):
    # Installed and importable here, yet the node could not import it: a
    # different interpreter, or a worker holding older state. Installing again
    # cannot help, so no button.
    monkeypatch.setattr(
        pip_runner, "distributions_for_module", lambda module: ["Flask"]
    )
    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    found = detect(_traceback("ModuleNotFoundError: No module named 'flask'"))
    assert found["installable"] is False
    assert found["reason"] == "installed-not-visible"
    assert found["distribution"] == "Flask"


def test_reports_an_installed_library_that_cannot_import(monkeypatch):
    # pip looks, finds a matching version, reports "already satisfied" and
    # changes nothing - so "Install" would be a lie. Carry the probe's reason.
    monkeypatch.setattr(
        pip_runner, "distributions_for_module", lambda module: ["rasterio"]
    )
    monkeypatch.setattr(
        pip_runner, "import_failures",
        lambda deps: {"rasterio": "ImportError: libgdal.so.30: cannot open"},
    )
    found = detect(_traceback("ModuleNotFoundError: No module named 'rasterio'"))
    assert found["installable"] is False
    assert found["reason"] == "installed-but-broken"
    assert found["distribution"] == "rasterio"
    assert "libgdal" in found["detail"]


# ── 4. One alias table, and one cheap path ──────────────────────────────────


@pytest.mark.parametrize(
    "module,distribution", sorted(dependency_scanner._PY_NAME_ALIAS.items())
)
def test_resolves_every_alias_the_manifest_scanner_knows(module, distribution):
    # Parametrized over the table itself: an entry added for the package
    # builder and not for this path would otherwise go unnoticed until a user
    # clicked Install on a name PyPI does not have.
    if module in getattr(sys, "stdlib_module_names", frozenset()):
        pytest.skip(f"{module} is stdlib on this interpreter")
    found = detect(_traceback(f"ModuleNotFoundError: No module named '{module}'"))
    assert found is not None
    # An alias may legitimately already be installed in this environment (PIL,
    # yaml); the claim under test is the name it maps to either way.
    assert found["distribution"] == distribution or found["reason"] in {
        "installed-not-visible", "installed-but-broken",
    }


def test_the_absent_case_spawns_no_subprocess(monkeypatch):
    # This runs on the response path of every failed node execution. The common
    # answer - "nothing provides it" - must not pay for an import probe.
    def explode(*args, **kwargs):  # pragma: no cover - the assertion is that it is not called
        raise AssertionError("import_failures was called for an absent module")

    monkeypatch.setattr(pip_runner, "import_failures", explode)
    found = detect(_traceback(
        "ModuleNotFoundError: No module named 'curio_absent_for_this_test'"
    ))
    assert found["installable"] is True


def test_never_raises_on_malformed_input(monkeypatch):
    # A diagnostic that turns one failure into two is worse than no diagnostic.
    monkeypatch.setattr(
        pip_runner, "distributions_for_module",
        lambda module: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert detect(_traceback("ModuleNotFoundError: No module named 'sklearn'")) is None
