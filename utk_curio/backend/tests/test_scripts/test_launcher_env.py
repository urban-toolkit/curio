"""``curio start`` flags to environment variables.

``set_environment_variables`` is the only translation layer between the
launcher's argparse flags and the env vars every server reads. Nothing else in
the suite imports ``utk_curio.cli.environment``, so this mapping has been unverified: the
backend tests set the env vars directly and never exercise the code that
derives them.

The mapping is also load-bearing in a non-obvious way. It writes these vars on
*every* start, so a value placed in a ``.env`` is overwritten (documented for
``--allow-publish`` in NODE-CATALOG.md); the flag is the only way to change them
when launching through ``curio.py``.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import utk_curio
from utk_curio.cli.environment import set_environment_variables


def _launcher_source() -> str:
    """The launcher's whole text: utk_curio/main.py and every utk_curio/cli module."""
    import utk_curio.cli as cli
    import utk_curio.main as launcher

    files = [Path(launcher.__file__)] + sorted(Path(cli.__file__).parent.glob("*.py"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


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
        "CURIO_EXEC_MEMORY_MB",
        "CURIO_DISCOVERY_ROOT",
        "CURIO_MODELS_ROOT",
        "CURIO_SOLVE_MAX_ATTEMPTS",
        "CURIO_SOLVE_NODE_BUDGET",
        "CURIO_SOLVE_SESSION_DEADLINE",
        "CURIO_SOLVE_BATCH_DEADLINE",
        "CURIO_VALIDATION_EXEC_TIMEOUT",
        "CURIO_VALIDATION_NODE_LIMIT",
        "CURIO_DISCOVERY_MAX_DOWNLOAD_MB",
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
    import utk_curio.cli.environment as environment_mod

    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(environment_mod, "_discover_exec_user",
                        lambda: environment_mod.DEFAULT_EXEC_USER)


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


def test_save_node_outputs_defaults_off_and_honours_the_env_var(monkeypatch):
    # Opt-in per node (#180): a dataflow should not accumulate a Computed
    # dataset for every node the user happens to run. There is no curio.py flag
    # for this - it only seeds a toggle every user can flip in the UI - so the
    # env var is the whole interface and must survive a launch through curio.py.
    set_environment_variables(**BASE)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "0"

    monkeypatch.setenv("CURIO_DEFAULT_SAVE_NODE_OUTPUT", "1")
    set_environment_variables(**BASE)
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


# ── Settings that used to be environment-only are curio.py arguments ───────


def _shipped_discovery_root():
    from utk_curio.backend.app.discovery.infrastructure import storage

    return storage.discovery_root()


def _shipped_models_root():
    from utk_curio.backend.app.model_catalog.infrastructure import storage

    return storage.models_root()


@pytest.mark.parametrize("arg, env_name, reader", [
    ("discovery_root", "CURIO_DISCOVERY_ROOT", _shipped_discovery_root),
    ("models_root", "CURIO_MODELS_ROOT", _shipped_models_root),
])
def test_a_shipped_root_flag_is_resolved_and_read_by_the_backend(tmp_path, arg, env_name, reader):
    nested = tmp_path / "a" / ".." / "shipped"
    set_environment_variables(**BASE, **{arg: str(nested)})
    assert Path(os.environ[env_name]) == (tmp_path / "shipped").resolve()
    assert Path(reader()).resolve() == (tmp_path / "shipped").resolve()


@pytest.mark.parametrize("env_name", ["CURIO_DISCOVERY_ROOT", "CURIO_MODELS_ROOT"])
def test_no_shipped_root_flag_leaves_its_var_unset(env_name):
    set_environment_variables(**BASE)
    assert env_name not in os.environ


def _budget(name):
    from utk_curio.backend.app.agents.application.solve import budgets

    return getattr(budgets, name)()


def _validation_timeout():
    from utk_curio.backend.app.execution import runner

    return runner.exec_timeout_s()


def _validation_node_limit():
    from utk_curio.backend.app.execution import runner

    return runner.validation_node_limit()


@pytest.mark.parametrize("arg, env_name, value, reader", [
    ("solve_max_attempts", "CURIO_SOLVE_MAX_ATTEMPTS", 12, lambda: _budget("solve_max_attempts")),
    ("solve_node_budget", "CURIO_SOLVE_NODE_BUDGET", 300, lambda: _budget("solve_node_budget_s")),
    ("solve_session_deadline", "CURIO_SOLVE_SESSION_DEADLINE", 600, lambda: _budget("solve_session_deadline_s")),
    ("solve_batch_deadline", "CURIO_SOLVE_BATCH_DEADLINE", 1800, lambda: _budget("solve_batch_deadline_s")),
    ("validation_exec_timeout", "CURIO_VALIDATION_EXEC_TIMEOUT", 120, _validation_timeout),
    ("validation_node_limit", "CURIO_VALIDATION_NODE_LIMIT", 40, _validation_node_limit),
])
def test_a_solve_flag_reaches_the_setting_the_backend_reads(arg, env_name, value, reader):
    set_environment_variables(**BASE, **{arg: value})
    assert os.environ[env_name] == str(value)
    assert reader() == value


def test_the_discovery_download_ceiling_flag_reaches_the_setting_the_backend_reads():
    from utk_curio.backend.app.discovery.domain import limits

    set_environment_variables(**BASE, discovery_max_download_mb=2048)
    assert os.environ["CURIO_DISCOVERY_MAX_DOWNLOAD_MB"] == "2048"
    assert limits.max_download_bytes() == 2048 * 1024 * 1024


def test_without_the_discovery_download_ceiling_flag_it_is_one_gibibyte():
    from utk_curio.backend.app.discovery.domain import limits

    set_environment_variables(**BASE)
    assert "CURIO_DISCOVERY_MAX_DOWNLOAD_MB" not in os.environ
    assert limits.max_download_bytes() == 1024 * 1024 * 1024


def test_a_discovery_download_ceiling_of_zero_is_refused_at_launch():
    with pytest.raises(ValueError, match="--discovery-max-download-mb"):
        set_environment_variables(**BASE, discovery_max_download_mb=0)


def test_save_node_outputs_flag_sets_the_toggles_default():
    set_environment_variables(**BASE, save_node_outputs=True)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "1"
    set_environment_variables(**BASE, save_node_outputs=False)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "0"


def test_without_the_save_node_outputs_flag_the_toggle_starts_off():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "0"


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

    def test_the_flag_set_is_exactly_these(self):
        """A guard on the guard: a new flag must be a decision, not a drift.

        The launcher grew thirteen of these at once, eight of which were
        either not ours to set (a run cap), unsafe as an argument (an API
        key), or belonged to a different subsystem entirely. Adding one back
        should require editing this list.
        """
        import re

        source = _launcher_source()
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
            # #615: the guest configuration, package builds and node workers.
            "--guest-llm-provider",
            "--guest-llm-base-url",
            "--guest-llm-model",
            "--js-registry-url",
            "--js-block-unpinned",
            "--js-parallelism",
            "--package-workers",
        }, sorted(flags)


class TestVariablesThatStayEnvOnly:
    """The three kinds that deliberately have no flag.

    Recorded as a test so removing one is a decision rather than an accident.
    """

    def test_parent_to_child_plumbing_has_no_flag(self):
        # Written by backend_runtime when it spawns a package backend, and by
        # install_preview_runner into the wrapper it generates. A user setting
        # these by hand would be configuring one subprocess invocation.
        source = _launcher_source()
        for key in ("CURIO_PKG_ENTRY", "CURIO_PKG_NET_ALLOWED", "CURIO_PREVIEW_REACTFLOW_UMD"):
            assert key not in source, key

    def test_test_only_switches_have_no_flag(self):
        # CURIO_TESTING_LLM_SCRIPT is read only when CURIO_TESTING is set;
        # exposing it on the launcher would advertise a test seam as an
        # operator feature.
        source = _launcher_source()
        assert "CURIO_TESTING_LLM_SCRIPT" not in source


# ── The address the frontend bundle is built against ────────────────────────


def test_backend_url_follows_the_backend_port():
    """The page must name the backend this launch actually starts.

    ``--backend-port`` alone moves the server; without this the UI's idea of
    where it is stayed behind, and the UI then called whatever Curio owned the
    old port.
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


def test_backend_url_argument_wins():
    """An operator terminating TLS or proxying needs the last word (--backend-url)."""
    set_environment_variables(**{**BASE, "backend_port": 5102, "backend_url": "https://curio.example.org/app/api"})
    assert os.environ["BACKEND_URL"] == "https://curio.example.org/app/api"


def test_an_inherited_backend_url_is_not_an_input(monkeypatch):
    """The address is curio.py's to decide: from --backend-url, or derived."""
    monkeypatch.setenv("BACKEND_URL", "https://someone-else.example.org")
    set_environment_variables(**{**BASE, "backend_port": 5102})
    assert os.environ["BACKEND_URL"] == "http://localhost:5102"


class TestExecMemoryFloor:
    """``--exec-memory-mb`` is clamped, not just passed through (#334).

    The number is spent by code that never sees the flag: ``codec`` sizes
    DuckDB's ``memory_limit`` against it, and that write happens inside the
    child's RLIMIT_AS cap. While the writer's limit was a fixed 256MB, an
    operator lowering the budget - which USAGE.md invites, since it sells the
    host ceiling as budget x parallelism - handed the child less headroom than
    DuckDB had been told it could spend. Deriving the writer's limit fixes the
    drift; this floor is the other half, enforced where the value enters.
    """

    def _floor(self):
        from utk_curio.sandbox.isolation.supervisor import MIN_EXEC_MEMORY_MB

        return MIN_EXEC_MEMORY_MB

    def test_a_workable_budget_is_passed_through_untouched(self):
        set_environment_variables(**BASE, exec_memory_mb=1024)
        assert os.environ["CURIO_EXEC_MEMORY_MB"] == "1024"

    def test_the_floor_itself_is_not_clamped(self):
        """An off-by-one here would move the documented floor."""
        set_environment_variables(**BASE, exec_memory_mb=self._floor())
        assert os.environ["CURIO_EXEC_MEMORY_MB"] == str(self._floor())

    def test_a_budget_below_the_floor_is_raised_to_it(self):
        set_environment_variables(**BASE, exec_memory_mb=16)
        assert os.environ["CURIO_EXEC_MEMORY_MB"] == str(self._floor())

    def test_a_nonsense_budget_is_raised_too(self):
        """Nothing else rejects this: argparse takes any int.

        A negative budget reached ``child._apply_rlimits`` as a cap below the
        interpreter's own footprint, which fails every allocation the child
        makes - and, as the module docstring records, once made a
        runaway-allocation test pass for the wrong reason.
        """
        for value in (-1, 0):
            set_environment_variables(**BASE, exec_memory_mb=value)
            assert os.environ["CURIO_EXEC_MEMORY_MB"] == str(self._floor()), value

    def test_the_clamp_says_so_rather_than_silently_moving_the_number(self, capsys):
        """An operator who asked for 16 and got 64 has to find out here.

        Silently honouring a different limit than the one asked for is how a
        host ends up over-committed: the ceiling USAGE.md quotes is budget x
        parallelism, and both factors have to be the real ones.
        """
        set_environment_variables(**BASE, exec_memory_mb=16)
        warning = capsys.readouterr().err
        assert "--exec-memory-mb" in warning
        assert "16" in warning and str(self._floor()) in warning
        # And points at the knob that actually solves the problem they had.
        assert "--exec-parallelism" in warning

    def test_an_omitted_flag_leaves_the_variable_unset(self):
        """The clamp must not start exporting a default nobody asked for.

        ``runner.IsolationConfig.from_environment`` supplies
        ``DEFAULT_LIMITS["memory_mb"]`` when the variable is absent, so writing
        one here would duplicate that default in a second place.
        """
        set_environment_variables(**BASE)
        assert "CURIO_EXEC_MEMORY_MB" not in os.environ


# ── --deploy requires isolation, or it does not start ───────────────────────


def _cannot_isolate(monkeypatch):
    """A host with no fork isolation to be had: macOS, Windows, a bare Linux."""
    from utk_curio.sandbox.isolation import mode as isolation_mode

    monkeypatch.setattr(isolation_mode, "capabilities", lambda: {
        "platform": "darwin", "fork": False, "rlimit": False,
        "seccomp": False, "linux": False,
    })


def test_deploy_refuses_to_start_where_it_cannot_isolate(monkeypatch):
    """Two shapes, not three.

    A deployment has accounts AND isolates; a local run has neither. The third
    shape -- accounts sharing one interpreter -- used to boot with a warning,
    which meant one user's ``pip install`` could change what another user's
    nodes import and the only protection was a gate on installs that nobody
    could see from the command they typed. Refusing is the honest answer: the
    operator asked for something this host cannot give.
    """
    _cannot_isolate(monkeypatch)
    # The suite runs under CURIO_TESTING, which is the exemption itself: clear
    # it to stand in for an operator's shell.
    monkeypatch.delenv("CURIO_TESTING", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        set_environment_variables(**BASE, deploy=True)

    message = str(exit_info.value)
    assert "--deploy needs isolated node execution" in message
    # It has to say what to do next, not just what it refused.
    assert "drop --deploy" in message


def test_a_test_rig_may_still_run_accounts_without_isolation(monkeypatch):
    """The exemption, and the only one.

    The e2e and stress harnesses boot ``--deploy`` to get the login page, on
    whatever machine the developer has, and create every account themselves.
    """
    _cannot_isolate(monkeypatch)
    monkeypatch.setenv("CURIO_TESTING", "1")

    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_ISOLATION"] == "off"


def test_a_local_run_on_the_same_host_is_untouched(monkeypatch):
    """No --deploy, no refusal: this is the everyday developer path."""
    _cannot_isolate(monkeypatch)
    monkeypatch.delenv("CURIO_TESTING", raising=False)

    set_environment_variables(**BASE)

    assert os.environ["CURIO_NO_AUTH"] == "1"
    assert os.environ["CURIO_ISOLATION"] == "off"


def test_deploy_that_can_isolate_starts_and_isolates(linux_host, monkeypatch):
    """The supported deployment shape still resolves to fork."""
    monkeypatch.setattr("utk_curio.cli.environment._discover_exec_user", lambda: "curio-exec")
    monkeypatch.delenv("CURIO_TESTING", raising=False)

    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_ISOLATION"] == "fork"


def test_the_testing_flag_declares_the_rig(monkeypatch):
    """``--testing`` is the flag form of what was an env var only.

    It has to be set before anything reads it: the database URL, the
    /api/testing routes and the isolation exemption all key off the same
    value, and two of those are decided while this function runs.
    """
    _cannot_isolate(monkeypatch)
    monkeypatch.delenv("CURIO_TESTING", raising=False)

    set_environment_variables(**BASE, deploy=True, testing=True)

    assert os.environ["CURIO_TESTING"] == "1"
    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_ISOLATION"] == "off"


def test_a_preset_testing_env_var_still_counts(monkeypatch):
    """The pytest rig imports the app in-process and has no command line."""
    _cannot_isolate(monkeypatch)
    monkeypatch.setenv("CURIO_TESTING", "1")

    set_environment_variables(**BASE, deploy=True)

    assert os.environ["CURIO_NO_AUTH"] == "0"


# ── Operator settings that were environment-only (#615) ─────────────────────
#
# Each is a curio.py argument now, written the way #614's are: only when the
# flag is passed, so a value already in the environment is still read.

#: Every variable a #615 flag writes.
OPERATOR_KEYS = (
    "GUEST_LLM_API_TYPE",
    "GUEST_LLM_BASE_URL",
    "GUEST_LLM_MODEL",
    "CURIO_MEDIA_CACHE_MAX_GB",
    "CURIO_DB_POOL_SIZE",
    "CURIO_DB_POOL_OVERFLOW",
    "CURIO_DB_POOL_TIMEOUT",
    "CURIO_PACKAGE_WORKERS",
    "CURIO_JS_PARALLELISM",
    "CURIO_JS_REGISTRY_URL",
    "CURIO_JS_BLOCK_UNPINNED",
    "CURIO_STATE_DIR",
    "CURIO_SHARED_GUEST_NAME",
    "CURIO_SHARED_GUEST_USERNAME",
    "COLLAB_CORS_ORIGINS",
    "COLLAB_NAMESPACE",
    "LOG_TO_STDOUT",
)

#: The flags that write them.
OPERATOR_FLAG_NAMES = (
    "--guest-llm-provider",
    "--guest-llm-base-url",
    "--guest-llm-model",
    "--media-cache-max-gb",
    "--db-pool-size",
    "--db-pool-overflow",
    "--db-pool-timeout",
    "--package-workers",
    "--js-parallelism",
    "--js-registry-url",
    "--js-block-unpinned",
    "--state-dir",
    "--shared-guest-name",
    "--shared-guest-username",
    "--collab-origins",
    "--collab-namespace",
    "--log-to-stdout",
)


@pytest.fixture(autouse=True)
def _isolate_operator_env():
    """Clear these before AND after, for the reason _isolate_agent_env gives."""
    saved = {k: os.environ.pop(k, None) for k in OPERATOR_KEYS}
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


def _fresh(module, expression):
    """*expression* as a server process started now reads it.

    The backend's and the sandbox's configs read these settings once, at
    import, so the reader is a new interpreter that inherits this environment,
    as the launcher's children do.
    """
    code = f"import json, {module} as m; print(json.dumps({expression}))"
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(utk_curio.__file__).resolve().parent.parent,
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _backend(expression):
    return lambda: _fresh("utk_curio.backend.config", expression)


def _sandbox(expression):
    return lambda: _fresh("utk_curio.sandbox.config", expression)


def _media_cache_bytes():
    from utk_curio.backend.app.discovery.application import cache_collection

    return cache_collection.cap_bytes()


def _package_workers():
    from utk_curio.backend.app.packages.infrastructure import backend_runtime

    return backend_runtime._default_worker_slots()


def _js_parallelism():
    from utk_curio.sandbox.app import worker

    return worker._default_js_parallelism()


def _js_policy(field):
    def read():
        from utk_curio.backend.app.packages.builder import deps

        return getattr(deps.policy_from_env(), field)

    return read


_POOL = "m.Config.SQLALCHEMY_ENGINE_OPTIONS"

#: (keyword, value passed, variable, value written, reader, what the reader returns)
OPERATOR_FLAGS = [
    pytest.param("guest_llm_provider", "anthropic", "GUEST_LLM_API_TYPE", "anthropic",
                 _backend("m.GUEST_LLM_API_TYPE"), "anthropic", id="guest-llm-provider"),
    pytest.param("guest_llm_base_url", "https://guest.example.test/v1", "GUEST_LLM_BASE_URL",
                 "https://guest.example.test/v1", _backend("m.GUEST_LLM_BASE_URL"),
                 "https://guest.example.test/v1", id="guest-llm-base-url"),
    pytest.param("guest_llm_model", "small-model", "GUEST_LLM_MODEL", "small-model",
                 _backend("m.GUEST_LLM_MODEL"), "small-model", id="guest-llm-model"),
    pytest.param("media_cache_max_gb", 2.5, "CURIO_MEDIA_CACHE_MAX_GB", "2.5",
                 _media_cache_bytes, int(2.5 * 1024**3), id="media-cache-max-gb"),
    pytest.param("db_pool_size", 16, "CURIO_DB_POOL_SIZE", "16",
                 _backend(f"{_POOL}['pool_size']"), 16, id="db-pool-size"),
    pytest.param("db_pool_overflow", 0, "CURIO_DB_POOL_OVERFLOW", "0",
                 _backend(f"{_POOL}['max_overflow']"), 0, id="db-pool-overflow"),
    pytest.param("db_pool_timeout", 5, "CURIO_DB_POOL_TIMEOUT", "5",
                 _backend(f"{_POOL}['pool_timeout']"), 5, id="db-pool-timeout"),
    pytest.param("package_workers", 3, "CURIO_PACKAGE_WORKERS", "3",
                 _package_workers, 3, id="package-workers"),
    pytest.param("js_parallelism", 5, "CURIO_JS_PARALLELISM", "5",
                 _js_parallelism, 5, id="js-parallelism"),
    pytest.param("js_registry_url", "https://registry.example.test/", "CURIO_JS_REGISTRY_URL",
                 "https://registry.example.test/", _js_policy("js_registry_url"),
                 "https://registry.example.test/", id="js-registry-url"),
    pytest.param("js_block_unpinned", True, "CURIO_JS_BLOCK_UNPINNED", "1",
                 _js_policy("block_unpinned_js"), True, id="js-block-unpinned"),
    pytest.param("js_block_unpinned", False, "CURIO_JS_BLOCK_UNPINNED", "0",
                 _js_policy("block_unpinned_js"), False, id="no-js-block-unpinned"),
    pytest.param("shared_guest_name", "Lab Guest", "CURIO_SHARED_GUEST_NAME", "Lab Guest",
                 _backend("m.CURIO_SHARED_GUEST_NAME"), "Lab Guest", id="shared-guest-name"),
    pytest.param("shared_guest_username", "lab_guest", "CURIO_SHARED_GUEST_USERNAME", "lab_guest",
                 _backend("m.CURIO_SHARED_GUEST_USERNAME"), "lab_guest", id="shared-guest-username"),
    pytest.param("collab_origins", "http://192.168.1.5:8080,http://192.168.1.6:8080",
                 "COLLAB_CORS_ORIGINS", "http://192.168.1.5:8080,http://192.168.1.6:8080",
                 _backend("m.COLLAB_CORS_ORIGINS"),
                 "http://192.168.1.5:8080,http://192.168.1.6:8080", id="collab-origins"),
    pytest.param("collab_namespace", "/team", "COLLAB_NAMESPACE", "/team",
                 _backend("m.COLLAB_NAMESPACE"), "/team", id="collab-namespace"),
    pytest.param("log_to_stdout", True, "LOG_TO_STDOUT", "1",
                 _backend("bool(m.Config.LOG_TO_STDOUT)"), True, id="log-to-stdout"),
    # Off is what the flag is for: .flaskenv turns an unset variable on.
    pytest.param("log_to_stdout", False, "LOG_TO_STDOUT", "",
                 _backend("bool(m.Config.LOG_TO_STDOUT)"), False, id="no-log-to-stdout-backend"),
    pytest.param("log_to_stdout", False, "LOG_TO_STDOUT", "",
                 _sandbox("bool(m.Config.LOG_TO_STDOUT)"), False, id="no-log-to-stdout-sandbox"),
]


@pytest.mark.parametrize("keyword, value, env_name, written, reader, read", OPERATOR_FLAGS)
def test_an_operator_flag_reaches_the_setting_its_server_reads(
    keyword, value, env_name, written, reader, read,
):
    set_environment_variables(**BASE, **{keyword: value})

    assert os.environ[env_name] == written
    assert reader() == read


# The tests below write os.environ directly: the isolation fixtures put each of
# these variables back, and a monkeypatch undo after them would delete it.


def test_an_empty_guest_base_url_sends_guests_to_the_providers_own_endpoint():
    """Unset, the guest configuration takes the deployment's endpoint; empty
    is how an operator gives guests the provider's own one instead."""
    os.environ["CURIO_DEFAULT_LLM_BASE_URL"] = "http://localhost:11434/v1"

    set_environment_variables(**BASE, guest_llm_base_url="")

    assert os.environ["GUEST_LLM_BASE_URL"] == ""
    assert _fresh("utk_curio.backend.config", "m.GUEST_LLM_BASE_URL") == ""


def test_omitted_operator_flags_leave_the_environment_alone():
    set_environment_variables(**BASE)
    for key in OPERATOR_KEYS:
        assert key not in os.environ, key

    for key in OPERATOR_KEYS:
        os.environ[key] = "from-the-environment"
    set_environment_variables(**BASE)
    for key in OPERATOR_KEYS:
        assert os.environ[key] == "from-the-environment", key


def test_the_state_dir_flag_is_resolved_and_read_by_the_backend(tmp_path):
    from utk_curio.backend.app.common import user_storage
    from utk_curio.backend.config import _is_testing
    from utk_curio.cli.environment import set_state_dir

    set_state_dir(str(tmp_path / "a" / ".." / "state"))

    state = (tmp_path / "state").resolve()
    assert Path(os.environ["CURIO_STATE_DIR"]) == state
    assert user_storage.curio_root() == (state / "test" if _is_testing() else state)


def test_without_the_state_dir_flag_the_variable_is_left_alone():
    from utk_curio.cli.environment import set_state_dir

    set_state_dir(None)
    assert "CURIO_STATE_DIR" not in os.environ

    os.environ["CURIO_STATE_DIR"] = "/srv/curio-state"
    set_state_dir(None)
    assert os.environ["CURIO_STATE_DIR"] == "/srv/curio-state"


def test_the_state_dir_is_set_before_the_launcher_opens_its_log(monkeypatch, tmp_path):
    """The launcher writes its own log into the state directory, so main() has
    to put the flag in the environment before setup_logging runs."""
    import utk_curio.main as launcher

    class _LogOpened(Exception):
        pass

    def setup_logging(server):
        raise _LogOpened(os.environ.get("CURIO_STATE_DIR"))

    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr("sys.argv", ["curio.py", "start", "--state-dir", str(tmp_path / "state")])
    monkeypatch.setattr(launcher, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, signal=lambda *args: None,
    ))
    monkeypatch.setattr(launcher, "setup_logging", setup_logging)

    with pytest.raises(_LogOpened) as opened:
        launcher.main()

    assert opened.value.args[0] == str((tmp_path / "state").resolve())


def _parser_flags():
    """Every flag main()'s parser declares, as its source spells them."""
    import utk_curio.main as launcher

    source = Path(launcher.__file__).read_text(encoding="utf-8")
    return set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source))


def _guides():
    docs = Path(utk_curio.__file__).resolve().parent.parent / "docs"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(docs.glob("*.md"))}


def _named_in(guides, flag):
    pattern = re.compile(re.escape(flag) + r"(?![a-z0-9-])")
    return [name for name, text in guides.items() if pattern.search(text)]


@pytest.mark.parametrize("flag", OPERATOR_FLAG_NAMES)
def test_each_operator_flag_is_an_argument_a_guide_names(flag):
    assert flag in _parser_flags()
    assert _named_in(_guides(), flag), f"no guide in docs/ names {flag}"


def test_every_curio_py_flag_is_named_in_a_guide():
    """A flag ships with the guide that tells an operator about it."""
    guides = _guides()
    missing = sorted(flag for flag in _parser_flags() if not _named_in(guides, flag))
    assert not missing, missing
