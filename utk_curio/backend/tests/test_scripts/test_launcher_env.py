"""``curio start`` flags to environment variables.

``set_environment_variables`` is the only translation layer between the
launcher's argparse flags and the env vars every server reads. Nothing else in
the suite imports ``utk_curio.main``, so this mapping has been unverified: the
backend tests set the env vars directly and never exercise the code that
derives them.

The mapping is also load-bearing in a non-obvious way. It writes these vars on
*every* start, so a value placed in a ``.env`` is overwritten (documented for
``--allow-publish`` in NODE-CATALOG.md); the flag is the only way to change them
when launching through ``curio.py``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from utk_curio.main import set_environment_variables

BASE = dict(
    backend_host="127.0.0.1",
    backend_port=5002,
    sandbox_host="127.0.0.1",
    sandbox_port=2000,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    # set_environment_variables mutates os.environ in place.
    for key in (
        "CURIO_CATALOG_ROOT",
        "CURIO_DEFAULT_SAVE_NODE_OUTPUT",
        "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH",
        "CURIO_SEED_EXAMPLES",
        "CURIO_RESEED_PACKAGES",
        "CURIO_NO_AUTH",
        "CURIO_NO_PROJECT",
        "ENABLE_COLLAB",
        "BACKEND_URL",
        "CURIO_ISOLATION",
        "CURIO_EXEC_USER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))


@pytest.fixture
def linux_host(monkeypatch):
    """Make the launcher resolve isolation as a complete Linux host would.

    ``resolve_mode`` is exercised for real; only the capability probe is
    replaced, so these tests answer "what does the launcher decide", not "what
    can this laptop do". Without it the whole fork half of the table is
    unreachable from macOS and Windows, which is where Curio is developed.
    """
    from utk_curio.sandbox.isolation import mode as isolation_mode

    monkeypatch.setattr(isolation_mode, "capabilities", lambda: {
        "platform": "linux", "fork": True, "rlimit": True,
        "seccomp": True, "linux": True,
    })


# ── Isolation is resolved by the launcher, not passed through ───────────────


def test_auto_is_exported_as_the_decision_it_resolves_to(linux_host):
    """'auto' is a request. Every reader downstream needs the answer.

    It used to be exported verbatim and decided later inside the sandbox, so
    the backend and the launcher's own runtime-install default were both
    holding a value that did not say what would actually happen.
    """
    set_environment_variables(**BASE)

    assert os.environ["CURIO_ISOLATION"] == "off"


def test_a_preset_isolation_is_a_request_and_is_honoured(linux_host, monkeypatch):
    """The CLI flag is gone; CURIO_ISOLATION is how a test stack still asks."""
    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    monkeypatch.setenv("CURIO_EXEC_USER", "somebody")
    set_environment_variables(**BASE)

    assert os.environ["CURIO_ISOLATION"] == "fork"


def test_fork_that_the_platform_cannot_give_is_exported_as_off(monkeypatch):
    """A local launch degrades rather than breaking the developer's laptop,
    and the exported value says so, instead of claiming an isolation that is
    not happening."""
    from utk_curio.sandbox.isolation import mode as isolation_mode

    monkeypatch.setattr(isolation_mode, "capabilities", lambda: {
        "platform": "win32", "fork": False, "rlimit": False,
        "seccomp": False, "linux": False,
    })
    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    set_environment_variables(**BASE)

    assert os.environ["CURIO_ISOLATION"] == "off"


def test_a_hosted_instance_that_cannot_isolate_refuses_at_launch(monkeypatch):
    """Fail-closed, and now one process earlier: the launcher raises instead of
    the sandbox refusing to start after everything else is already up.

    Only for an EXPLICIT request. The --deploy default degrades instead, which
    is what keeps `curio.py start --deploy` working on Windows and macOS.
    """
    from utk_curio.sandbox.isolation import mode as isolation_mode

    monkeypatch.setattr(isolation_mode, "capabilities", lambda: {
        "platform": "win32", "fork": False, "rlimit": False,
        "seccomp": False, "linux": False,
    })
    monkeypatch.setenv("CURIO_ISOLATION", "fork")
    with pytest.raises(isolation_mode.IsolationUnavailable):
        set_environment_variables(**BASE, deploy=True)


# ── A deployment isolates by default, where it can ──────────────────────────


@pytest.fixture
def has_exec_account(monkeypatch):
    """A root launch on a host carrying the conventional execution account."""
    import utk_curio.main as main_mod

    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(main_mod, "_discover_exec_user",
                        lambda: main_mod.DEFAULT_EXEC_USER)


def test_a_deployment_that_can_isolate_does(linux_host, has_exec_account):
    """The point of the change, and the configuration the image ships."""
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "fork"
    assert os.environ["CURIO_EXEC_USER"] == "curio-exec"


def test_a_local_launch_does_not_isolate_even_where_it_could(
    linux_host, has_exec_account,
):
    """Isolation separates users from each other; locally there is one."""
    set_environment_variables(**BASE)

    assert os.environ["CURIO_ISOLATION"] == "off"


def test_a_deployment_not_running_as_root_still_boots(linux_host, monkeypatch):
    """setuid is how the boundary is applied, so an unprivileged launch has
    nothing to drop to and the default must decline rather than hand the
    sandbox a mode it will refuse to serve."""
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "off"
    assert os.environ["CURIO_EXEC_USER"] == ""


def test_a_deployment_without_the_account_still_boots(linux_host, monkeypatch):
    """Same decline, the other way to get there: root, but no such account.

    BOTH halves are forced, because the answer otherwise depends on the host
    this suite runs on. CI runs as root inside an image that HAS curio-exec,
    a developer laptop is neither, and a test that reads the real environment
    passes in one and fails in the other.
    """
    import pwd

    def _no_such_account(name):
        raise KeyError(name)

    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(pwd, "getpwnam", _no_such_account)
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "off"
    assert os.environ["CURIO_EXEC_USER"] == ""


def test_a_deployment_on_a_platform_that_cannot_isolate_still_boots(
    monkeypatch, has_exec_account,
):
    """--deploy has to work on Windows. A DEFAULT never refuses to boot."""
    from utk_curio.sandbox.isolation import mode as isolation_mode

    monkeypatch.setattr(isolation_mode, "capabilities", lambda: {
        "platform": "win32", "fork": False, "rlimit": False,
        "seccomp": False, "linux": False,
    })
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "off"


def test_an_empty_exec_user_forces_none_even_as_root(linux_host, monkeypatch):
    """How a test stack asks for the no-execution-user shape on a host that
    has the account: docker-compose.ci-isolated.yml runs as root in an image
    containing curio-exec and exists to exercise exactly that."""
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("CURIO_EXEC_USER", "")
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "off"
    assert os.environ["CURIO_EXEC_USER"] == ""


def test_a_preset_exec_user_beats_discovery(linux_host, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("CURIO_EXEC_USER", "someone-else")
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_EXEC_USER"] == "someone-else"


def test_isolation_off_beats_the_deploy_default(linux_host, has_exec_account,
                                                monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_ISOLATION"] == "off"


def test_auth_and_examples_together_is_the_combination_200_needed():
    """`--deploy --with-examples` must turn both on at once.

    This pair is the reported configuration for #200: a signed-in account with
    the examples seeded. The e2e harness booted multi-user but never
    ``--with-examples``, which is why nothing caught the empty gallery.
    """
    set_environment_variables(**BASE, deploy=True, with_examples=True)

    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_SEED_EXAMPLES"] == "1"


def test_examples_are_off_unless_asked_for():
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_SEED_EXAMPLES"] == "0"


def test_deploy_alone_does_not_seed_examples():
    """It used to, and that is now the harness's configuration.

    The e2e stack boots --deploy because that is the only way to get a login
    page, and two suites exist to cover multi-user WITHOUT examples. Seeding
    has to be asked for; docker-compose.deploy.yml asks.
    """
    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_SEED_EXAMPLES"] == "0"


def test_deploy_is_the_only_way_to_turn_auth_on():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_NO_AUTH"] == "1"

    set_environment_variables(**BASE, deploy=True)
    assert os.environ["CURIO_NO_AUTH"] == "0"


def test_no_project_still_skips_both_pages():
    set_environment_variables(**BASE, no_project=True)

    assert os.environ["CURIO_NO_AUTH"] == "1"
    assert os.environ["CURIO_NO_PROJECT"] == "1"


def test_save_node_outputs_defaults_off_and_can_be_turned_on():
    # Opt-in per node (#180): a dataflow should not accumulate a Computed
    # dataset for every node the user happens to run.
    set_environment_variables(**BASE)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "0"

    set_environment_variables(**BASE, save_node_outputs=True)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "1"


def test_allow_publish_defaults_on_and_can_be_locked_down():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_ALLOW_FACTORY_CATALOG_PUBLISH"] == "1"

    set_environment_variables(**BASE, allow_publish=False)
    assert os.environ["CURIO_ALLOW_FACTORY_CATALOG_PUBLISH"] == "0"


def test_catalog_root_is_expanded_and_resolved(tmp_path):
    nested = tmp_path / "a" / ".." / "catalog"
    set_environment_variables(**BASE, catalog_root=str(nested))
    got = os.environ["CURIO_CATALOG_ROOT"]
    assert Path(got).is_absolute()
    assert ".." not in got, "the path must be resolved, not passed through"
    assert Path(got) == (tmp_path / "catalog").resolve()


def test_catalog_root_expands_a_user_home_prefix():
    set_environment_variables(**BASE, catalog_root="~/curio-catalog")
    got = Path(os.environ["CURIO_CATALOG_ROOT"])
    assert "~" not in str(got)
    assert got == (Path.home() / "curio-catalog").resolve()


def test_no_catalog_root_leaves_the_var_unset():
    # The guard matters: writing an empty CURIO_CATALOG_ROOT would override the
    # default <repo_root>/datasets with the process CWD.
    set_environment_variables(**BASE)
    assert "CURIO_CATALOG_ROOT" not in os.environ

    set_environment_variables(**BASE, catalog_root="")
    assert "CURIO_CATALOG_ROOT" not in os.environ


def test_deploy_forces_auth_and_projects_on():
    set_environment_variables(**BASE, deploy=True)
    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_NO_PROJECT"] == "0"


def test_a_plain_start_skips_auth():
    # This is what the Docker image's default command does, and why the deploy
    # compose overlay is mandatory (see DEPLOYMENT.md).
    set_environment_variables(**BASE)
    assert os.environ["CURIO_NO_AUTH"] == "1"


def test_auth_flag_requires_login_without_deploy():
    set_environment_variables(**BASE, deploy=True)
    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_NO_PROJECT"] == "0"


def test_no_project_implies_no_auth():
    set_environment_variables(**BASE, no_project=True)
    assert os.environ["CURIO_NO_PROJECT"] == "1"
    assert os.environ["CURIO_NO_AUTH"] == "1"


def test_only_with_examples_seeds_examples():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "0"

    set_environment_variables(**BASE, with_examples=True)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "1"

    # --deploy used to imply this. It cannot any more: the e2e harness boots
    # --deploy for the login page and must not seed.
    set_environment_variables(**BASE, deploy=True)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "0"


# --------------------------------------------------------------------------- #
# The agent catalog and package-build knobs
# --------------------------------------------------------------------------- #
#
# Both features arrived configured entirely through the environment. Curio's
# convention is a documented flag whose help names the variable it sets, so
# these are the argparse side of that. The three kinds that stay env-only are
# asserted below too, so a later change has to be deliberate about it.

AGENT_AND_BUILD_KEYS = (
    "CURIO_DEFAULT_LLM_API_TYPE",
    "CURIO_DEFAULT_LLM_BASE_URL",
    "CURIO_DEFAULT_LLM_MODEL",
    "GUEST_LLM_API_KEY",
    "CURIO_SEARCH_URL",
)

#: Variables an operator may set, that deliberately have NO launcher flag.
#: Each is asserted flagless in TestVariablesThatStayEnvOnly below.
NO_FLAG_KEYS = (
    # A key in argv is visible in the process list to every user on the host.
    "CURIO_DEFAULT_LLM_API_KEY",
    # The package-build subsystem, which is not part of the agent catalog.
    "CURIO_BUILD_ESBUILD",
    "CURIO_BUILD_PREVIEW_RUNNER",
    "CURIO_BUILD_PREVIEW_POLICY",
    "CURIO_JS_REGISTRY_URL",
    "CURIO_JS_BLOCK_UNPINNED",
    "CURIO_BACKEND_SANDBOX_PYTHON",
)


@pytest.fixture(autouse=True)
def _isolate_agent_env():
    """Clear these before AND after.

    ``set_environment_variables`` mutates ``os.environ`` in place, so a value
    written here outlives the test. Clearing only on the way in left
    CURIO_BUILD_ESBUILD and friends set for every suite that ran afterwards -
    which surfaced as six unrelated failures in test_agents, but only when the
    two directories were collected together.
    """
    saved = {k: os.environ.pop(k, None) for k in AGENT_AND_BUILD_KEYS + NO_FLAG_KEYS}
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


class TestAgentAndBuildFlags:
    def test_every_flag_reaches_its_variable(self):
        set_environment_variables(
            **BASE,
            llm_provider="anthropic",
            llm_base_url="https://example.test/v1",
            llm_model="some-model",
            guest_llm_api_key="gk",
            agent_search_url="https://search.test/?q={query}",
        )
        assert os.environ["CURIO_DEFAULT_LLM_API_TYPE"] == "anthropic"
        assert os.environ["CURIO_DEFAULT_LLM_BASE_URL"] == "https://example.test/v1"
        assert os.environ["CURIO_DEFAULT_LLM_MODEL"] == "some-model"
        assert os.environ["GUEST_LLM_API_KEY"] == "gk"
        assert os.environ["CURIO_SEARCH_URL"] == "https://search.test/?q={query}"

    def test_omitted_flags_leave_the_environment_alone(self):
        """Unlike the boolean knobs above, these are absent rather than "0".

        An operator who configured a provider through the environment (or a
        .env) must not have it cleared by a start that simply did not repeat
        the flag - an empty CURIO_DEFAULT_LLM_MODEL means "no provider", which
        would silently disable every AI surface.
        """
        set_environment_variables(**BASE)
        for key in AGENT_AND_BUILD_KEYS:
            assert key not in os.environ, key

    def test_the_flag_set_is_exactly_these_five(self):
        """A guard on the guard: a new flag must be a decision, not a drift.

        The launcher grew thirteen of these at once, eight of which were
        either not ours to set (a run cap), unsafe as an argument (an API
        key), or belonged to a different subsystem entirely. Adding one back
        should require editing this list.
        """
        import re

        import utk_curio.main as launcher

        source = Path(launcher.__file__).read_text(encoding="utf-8")
        # Read from source rather than by building the parser: the parser is
        # constructed inside main(), and TestVariablesThatStayEnvOnly below
        # already reads the file the same way.
        flags = set(
            re.findall(
                r'"(--(?:llm|guest-llm|agent|build|js|package)-[a-z-]+)"', source
            )
        )
        assert flags == {
            "--llm-provider",
            "--llm-base-url",
            "--llm-model",
            "--guest-llm-api-key",
            "--agent-search-url",
        }, sorted(flags)


class TestVariablesThatStayEnvOnly:
    """The three kinds that deliberately have no flag.

    Recorded as a test so removing one is a decision rather than an accident.
    """

    def test_parent_to_child_plumbing_has_no_flag(self):
        # Written by backend_runtime when it spawns a package backend, and by
        # install_preview_runner into the wrapper it generates. A user setting
        # these by hand would be configuring one subprocess invocation.
        import utk_curio.main as launcher

        source = Path(launcher.__file__).read_text(encoding="utf-8")
        for key in ("CURIO_PKG_ENTRY", "CURIO_PKG_NET_ALLOWED", "CURIO_PREVIEW_REACTFLOW_UMD"):
            assert key not in source, key

    def test_test_only_switches_have_no_flag(self):
        # CURIO_TESTING_LLM_SCRIPT is read only when CURIO_TESTING is set;
        # exposing it on the launcher would advertise a test seam as an
        # operator feature.
        import utk_curio.main as launcher

        source = Path(launcher.__file__).read_text(encoding="utf-8")
        assert "CURIO_TESTING_LLM_SCRIPT" not in source


# ── The address the frontend bundle is built against ────────────────────────


def test_backend_url_follows_the_backend_port():
    """The bundle must be built for the backend this launch actually starts.

    ``BACKEND_URL`` is substituted into the frontend at BUILD time. It used to
    come only from a hand-maintained ``frontend/urban-workflows/.env``, so
    ``--backend-port`` alone moved the server without moving the UI's idea of
    where it is -- and the UI then called whatever Curio owned the old port.
    """
    set_environment_variables(**{**BASE, "backend_port": 5102})

    assert os.environ["BACKEND_URL"] == "http://localhost:5102"


def test_a_loopback_backend_is_addressed_as_localhost():
    """127.0.0.1 and localhost are different ORIGINS to the browser.

    The backend binds 127.0.0.1 by default, but the page is served from
    localhost, so baking the literal bind address in would make every request
    cross-origin.
    """
    set_environment_variables(**{**BASE, "backend_host": "127.0.0.1"})
    assert os.environ["BACKEND_URL"].startswith("http://localhost:")

    set_environment_variables(**{**BASE, "backend_host": "0.0.0.0"})
    assert os.environ["BACKEND_URL"].startswith("http://localhost:")


def test_a_real_host_is_kept():
    """A deployment behind a hostname must not be rewritten to localhost."""
    set_environment_variables(**{**BASE, "backend_host": "curio.example.org"})
    assert os.environ["BACKEND_URL"] == "http://curio.example.org:5002"


def test_an_explicit_backend_url_wins(monkeypatch):
    """An operator terminating TLS or proxying needs the last word.

    Everything else here is derived, so this is the one escape hatch -- hence
    ``setdefault`` rather than an unconditional write, unlike its neighbours.
    """
    monkeypatch.setenv("BACKEND_URL", "https://curio.example.org")
    set_environment_variables(**{**BASE, "backend_port": 5102})
    assert os.environ["BACKEND_URL"] == "https://curio.example.org"
