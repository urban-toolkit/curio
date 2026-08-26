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
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))


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
    set_environment_variables(**BASE, auth=True)
    assert os.environ["CURIO_NO_AUTH"] == "0"
    assert os.environ["CURIO_NO_PROJECT"] == "0"


def test_no_project_implies_no_auth():
    set_environment_variables(**BASE, no_project=True)
    assert os.environ["CURIO_NO_PROJECT"] == "1"
    assert os.environ["CURIO_NO_AUTH"] == "1"


def test_deploy_seeds_examples_like_with_examples():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "0"

    set_environment_variables(**BASE, with_examples=True)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "1"

    set_environment_variables(**BASE, deploy=True)
    assert os.environ["CURIO_SEED_EXAMPLES"] == "1"


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
    "CURIO_DEFAULT_LLM_API_KEY",
    "GUEST_LLM_API_KEY",
    "CURIO_AGENT_RUNS_PER_DAY",
    "CURIO_SEARCH_URL",
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
    saved = {k: os.environ.pop(k, None) for k in AGENT_AND_BUILD_KEYS}
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
            llm_api_key="k",
            guest_llm_api_key="gk",
            agent_runs_per_day=25,
            agent_search_url="https://search.test/?q={query}",
            build_esbuild="/usr/bin/esbuild",
            build_preview_runner="/usr/bin/preview",
            build_preview_policy="skip",
            js_registry_url="https://registry.test",
            js_block_unpinned=True,
            package_backend_python="/usr/bin/python3",
        )
        assert os.environ["CURIO_DEFAULT_LLM_API_TYPE"] == "anthropic"
        assert os.environ["CURIO_DEFAULT_LLM_BASE_URL"] == "https://example.test/v1"
        assert os.environ["CURIO_DEFAULT_LLM_MODEL"] == "some-model"
        assert os.environ["CURIO_DEFAULT_LLM_API_KEY"] == "k"
        assert os.environ["GUEST_LLM_API_KEY"] == "gk"
        assert os.environ["CURIO_AGENT_RUNS_PER_DAY"] == "25"
        assert os.environ["CURIO_SEARCH_URL"] == "https://search.test/?q={query}"
        assert os.environ["CURIO_BUILD_ESBUILD"] == "/usr/bin/esbuild"
        assert os.environ["CURIO_BUILD_PREVIEW_RUNNER"] == "/usr/bin/preview"
        assert os.environ["CURIO_BUILD_PREVIEW_POLICY"] == "skip"
        assert os.environ["CURIO_JS_REGISTRY_URL"] == "https://registry.test"
        assert os.environ["CURIO_JS_BLOCK_UNPINNED"] == "1"
        assert os.environ["CURIO_BACKEND_SANDBOX_PYTHON"] == "/usr/bin/python3"

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

    def test_js_block_unpinned_is_only_set_when_asked(self):
        set_environment_variables(**BASE, js_block_unpinned=False)
        assert "CURIO_JS_BLOCK_UNPINNED" not in os.environ


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
