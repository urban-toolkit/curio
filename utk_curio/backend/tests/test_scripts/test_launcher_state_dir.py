"""``--state-dir`` moves the data folder with the rest of ``.curio``.

USAGE.md says ``--state-dir`` is "where Curio keeps its state", and
DATA-CATALOG.md says ``CURIO_STATE_DIR`` "moves ``.curio/``". The launcher
moved every user's store, the caches and its log there, but set
``CURIO_SHARED_DATA`` from the folder Curio starts in. So the node outputs and
``curio_data.duckdb`` stayed in ``./.curio/data`` of the launch folder. The
backend's own fallbacks (the monitor's storage, the media folders) already
look for the data folder in the state folder.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from utk_curio.cli import environment
from utk_curio.cli.environment import set_environment_variables, set_state_dir

BASE = dict(
    backend_host="127.0.0.1",
    backend_port=5002,
    sandbox_host="127.0.0.1",
    sandbox_port=2000,
)


@pytest.fixture(autouse=True)
def _launch_folder(monkeypatch, tmp_path):
    """A start from an empty folder, with no data or state folder named, and
    the environment as it was after the test: the launcher writes many
    variables."""
    saved = dict(os.environ)
    monkeypatch.chdir(tmp_path)
    for key in ("CURIO_SHARED_DATA", "CURIO_STATE_DIR", "CURIO_LAUNCH_CWD"):
        os.environ.pop(key, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _start(state_dir=None):
    set_state_dir(state_dir)
    set_environment_variables(**BASE)
    return Path(os.environ["CURIO_SHARED_DATA"])


def test_the_data_folder_is_in_the_state_folder(tmp_path):
    state = tmp_path / "state"

    assert _start(state) == state / "data"


def test_the_data_folder_is_in_the_state_folder_a_relative_path_names(tmp_path):
    assert _start("elsewhere/state") == tmp_path / "elsewhere" / "state" / "data"


def test_without_a_state_folder_the_data_folder_is_in_the_launch_folder(tmp_path):
    assert _start() == tmp_path.resolve() / ".curio" / "data"


def test_a_data_folder_named_by_its_variable_wins_over_the_state_folder(tmp_path):
    os.environ["CURIO_SHARED_DATA"] = str(tmp_path / "own-data")

    assert _start(tmp_path / "state") == tmp_path / "own-data"


@pytest.fixture
def warnings(monkeypatch):
    said = []
    monkeypatch.setattr(environment, "log_warning", said.append)
    return said


def test_a_start_says_where_the_earlier_node_outputs_stay(tmp_path, warnings):
    """A start with --state-dir before this one kept its node outputs in the
    launch folder. Nothing moves them, so the start says where they are."""
    earlier = tmp_path / ".curio" / "data"
    earlier.mkdir(parents=True)

    data = _start(tmp_path / "state")

    assert [warning for warning in warnings if str(earlier) in warning and str(data) in warning], warnings


def test_a_start_with_no_earlier_node_outputs_says_nothing_of_them(tmp_path, warnings):
    _start(tmp_path / "state")

    assert not [warning for warning in warnings if ".curio/data" in warning or "node outputs" in warning], warnings


def test_a_start_without_a_state_folder_says_nothing_of_its_node_outputs(tmp_path, warnings):
    (tmp_path / ".curio" / "data").mkdir(parents=True)

    _start()

    assert not [warning for warning in warnings if "node outputs" in warning], warnings
