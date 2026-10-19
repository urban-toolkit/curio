"""A sign-in test skips before its page opens, on a stack without sign-in.

``test_frontend/early_guards.py`` finds the guards an e2e test's body starts
with and calls them before the test's fixtures. Small functions stand in for
e2e tests here, on fake items, and the backend's ``/api/config/public`` answer
is faked, so no stack is needed. The last test runs a real pytest session, to
pin what JUnit records: CI compares those skips between runs.
"""

import functools
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_frontend import early_guards
from utk_curio.backend.tests.test_frontend.utils import environment
from utk_curio.backend.tests.test_frontend.utils.environment import (
    require_project_page,
    require_user_auth,
)

REPO = Path(__file__).resolve().parents[3]

#: /api/config/public of a stack without sign-in (test-isolated's), of one with
#: it (the other e2e jobs'), and of one without the projects page.
NO_SIGN_IN = {"curio_no_auth": True, "curio_no_project": False, "skip_project_page": False}
SIGN_IN = {"curio_no_auth": False, "curio_no_project": False, "skip_project_page": False}
NO_PROJECTS = {"curio_no_auth": True, "curio_no_project": True, "skip_project_page": True}


# Stand-ins for e2e tests, not named test_* so that pytest leaves them alone.

def guard_first(page):
    require_user_auth()
    page.goto("/")


def docstring_then_guard(page):
    """A docstring is not a statement that runs."""
    require_user_auth()


def _returns_it(function):
    function.tagged = True
    return function


@_returns_it
@pytest.mark.parametrize("kind", ["a", "b"])
def decorated(page, kind):
    require_user_auth()


class Holder:
    def method(self, page):
        require_user_auth()


def project_guard_then_guard(page):
    require_project_page()
    require_user_auth()


def guard_after_a_statement(page):
    page.goto("/")
    require_user_auth()


def guard_inside_an_if(page):
    if page:
        require_user_auth()


def _signs_in(page):
    require_user_auth()


def guard_through_a_helper(page):
    _signs_in(page)


def project_guard_only(page):
    require_project_page()
    _signs_in(page)


def _wraps(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return function(*args, **kwargs)
    return wrapper


@_wraps
def wrapped(page):
    require_user_auth()


def guard_of_the_same_name(page, require_user_auth):
    require_user_auth()


#: Their bodies start with the sign-in guard: it runs before their fixtures.
EARLY = [guard_first, docstring_then_guard, decorated, Holder.method, project_guard_then_guard]
#: Their bodies call it later, conditionally, through a helper or a wrapper, or
#: call something else of that name: their bodies decide, as before.
LEFT_TO_THE_BODY = [guard_after_a_statement, guard_inside_an_if, guard_through_a_helper,
                    project_guard_only, wrapped, guard_of_the_same_name]


@pytest.fixture
def backend(monkeypatch):
    """Sets what the backend answers on /api/config/public; None is no answer."""
    def answer(config):
        monkeypatch.setattr(environment, "_fetch_public_config", lambda: config)
    return answer


def _items(*functions):
    return [SimpleNamespace(function=function, stash=pytest.Stash()) for function in functions]


def _collected(items, environ=None):
    """The plugin after collecting ``items``, against a stack that is already up."""
    plugin = early_guards.EarlyGuards(
        environ={"CURIO_E2E_USE_EXISTING": "1"} if environ is None else environ)
    plugin.pytest_collection_modifyitems(items=items)
    return plugin


def _raised_from(excinfo):
    """Where a skip was raised, as JUnit names it: the last frame pytest does not hide."""
    where, tb = None, excinfo.tb
    while tb is not None:
        frame = tb.tb_frame
        if not (frame.f_locals.get("__tracebackhide__") or frame.f_globals.get("__tracebackhide__")):
            where = (frame.f_code.co_filename, tb.tb_lineno, frame.f_code.co_name)
        tb = tb.tb_next
    return where


def test_the_guards_run_early_are_the_ones_the_body_starts_with_in_its_order():
    for function in (guard_first, docstring_then_guard, decorated, Holder.method):
        assert early_guards.leading_guards(function) == (require_user_auth,), function.__name__
    assert early_guards.leading_guards(project_guard_then_guard) == (
        require_project_page, require_user_auth)
    for function in LEFT_TO_THE_BODY:
        assert early_guards.leading_guards(function) == (), function.__name__


def test_without_sign_in_the_test_skips_before_its_fixtures_as_its_body_would(backend):
    backend(NO_SIGN_IN)
    with pytest.raises(pytest.skip.Exception) as in_the_body:
        require_user_auth()
    items = _items(*EARLY)
    plugin = _collected(items)
    for item in items:
        with pytest.raises(pytest.skip.Exception) as early:
            plugin.pytest_runtest_setup(item)
        assert early.value.msg == in_the_body.value.msg == environment.USER_AUTH_REQUIRED
        # Raised by the guard itself, on its own line: the file and line JUnit
        # records with the reason are the ones a skip in the body gives.
        assert _raised_from(early) == _raised_from(in_the_body)
        assert _raised_from(early)[2] == "require_user_auth"


def test_with_sign_in_the_test_runs(backend):
    backend(SIGN_IN)
    items = _items(*EARLY)
    plugin = _collected(items)
    for item in items:
        plugin.pytest_runtest_setup(item)  # no skip: the fixtures and the body run


def test_a_later_call_skips_in_the_body_as_before(backend):
    backend(NO_SIGN_IN)
    items = _items(*LEFT_TO_THE_BODY)
    plugin = _collected(items)
    for item in items:
        plugin.pytest_runtest_setup(item)  # no skip before the fixtures


def test_a_guard_before_the_sign_in_guard_still_gives_its_own_reason(backend):
    backend(NO_PROJECTS)
    with pytest.raises(pytest.skip.Exception) as in_the_body:
        require_project_page()
    [item] = _items(project_guard_then_guard)
    plugin = _collected([item])
    with pytest.raises(pytest.skip.Exception) as early:
        plugin.pytest_runtest_setup(item)
    assert early.value.msg == in_the_body.value.msg == "This test requires CURIO_NO_PROJECT=0"
    assert _raised_from(early) == _raised_from(in_the_body)


def test_a_run_that_boots_its_own_stack_leaves_every_test_to_its_body(backend):
    backend(NO_SIGN_IN)
    items = _items(*EARLY)
    plugin = _collected(items, environ={})
    for item in items:
        plugin.pytest_runtest_setup(item)


def test_nothing_is_decided_early_while_the_backend_has_not_answered(backend, monkeypatch):
    # The guards would fall back to this process's environment, which need not
    # be the stack's, so the body decides.
    monkeypatch.setenv("CURIO_NO_AUTH", "1")
    backend(None)
    items = _items(*EARLY)
    plugin = _collected(items)
    for item in items:
        plugin.pytest_runtest_setup(item)


def test_an_item_that_is_not_a_python_function_is_left_alone(backend):
    backend(NO_SIGN_IN)
    item = SimpleNamespace(stash=pytest.Stash())  # a doctest, or another plugin's item
    plugin = _collected([item])
    plugin.pytest_runtest_setup(item)


CONFTEST = '''
from utk_curio.backend.tests.test_frontend import early_guards
from utk_curio.backend.tests.test_frontend.utils import environment

# The answer of a stack without sign-in, as on test-isolated.
environment._fetch_public_config = lambda: {"curio_no_auth": True}


def pytest_configure(config):
    config.pluginmanager.register(early_guards.EarlyGuards(), "curio-early-guards")
'''

TESTS = '''
import pytest

from utk_curio.backend.tests.test_frontend.utils.environment import require_user_auth


@pytest.fixture
def opened_page(request):
    """Stands for the page and the database reset an e2e test's fixtures set up."""
    with open("opened.txt", "a", encoding="utf-8") as log:
        log.write(request.node.name + "\\n")


def test_skips_before_its_fixtures(opened_page):
    require_user_auth()


def test_skips_in_its_body(opened_page):
    reached = True
    require_user_auth()


@pytest.mark.skipif(True, reason="a mark is judged before the guards")
def test_marked(opened_page):
    require_user_auth()
'''


def test_junit_records_an_early_skip_as_it_records_a_skip_in_the_body(tmp_path):
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "test_guarded.py").write_text(TESTS, encoding="utf-8")
    junit = tmp_path / "junit.xml"
    env = {**os.environ, "PYTHONPATH": str(REPO), "CURIO_E2E_USE_EXISTING": "1"}
    env.pop("PYTEST_ADDOPTS", None)  # CI's points at the unit suite's own JUnit file
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         f"--junitxml={junit}", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True, env=env, timeout=600,
    )
    assert run.returncode == 0, f"{run.stdout[-3000:]}\n{run.stderr[-3000:]}"
    skips = {case.get("name"): case.find("skipped") for case in ET.parse(junit).iter("testcase")}
    early, in_the_body = skips["test_skips_before_its_fixtures"], skips["test_skips_in_its_body"]
    assert early.get("message") == in_the_body.get("message") == environment.USER_AUTH_REQUIRED
    assert early.text == in_the_body.text
    assert f"{os.sep}environment.py:" in early.text
    assert skips["test_marked"].get("message") == "a mark is judged before the guards"
    opened = (tmp_path / "opened.txt").read_text(encoding="utf-8").split()
    assert opened == ["test_skips_in_its_body"], "a fixture was set up before the early skip"
