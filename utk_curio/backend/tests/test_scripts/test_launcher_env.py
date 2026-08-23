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


def test_save_node_outputs_defaults_on_and_can_be_turned_off():
    set_environment_variables(**BASE)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "1"

    set_environment_variables(**BASE, save_node_outputs=False)
    assert os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] == "0"


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
