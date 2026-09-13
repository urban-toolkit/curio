"""Does ``scripts/repro_zygote_fork_crash.py`` draw the right conclusion?

The loop itself needs Linux and a CI image, so it is not run here. What can
quietly mislead is the arithmetic and the verdict built on it, and those are
plain functions.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from utk_curio.backend.app.projects.seed import _repo_root
from utk_curio.sandbox.isolation import zygote

REPO_ROOT = str(_repo_root())
SCRIPT = os.path.join(REPO_ROOT, "scripts", "repro_zygote_fork_crash.py")


@pytest.fixture(scope="module")
def repro():
    spec = importlib.util.spec_from_file_location("repro_zygote_fork_crash", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _variant(crashes, runs=600):
    return {"crashes": crashes, "runs": runs}


def test_the_fisher_test_reproduces_a_known_value(repro):
    # 2 of 36 in one group against 0 of 252 in the other.
    assert repro.one_sided_fisher(2, 36, 0, 252) == pytest.approx(0.0152, abs=1e-4)


def test_no_crashes_is_no_evidence(repro):
    assert repro.one_sided_fisher(0, 300, 0, 300) == 1.0


@pytest.mark.parametrize(
    "baseline, released, label",
    [
        (_variant(13), _variant(0), "SUPPORTED"),
        (_variant(2), _variant(0), "SUGGESTIVE"),
        (_variant(0), _variant(0), "NOT REPRODUCED"),
        (_variant(13), _variant(1), "NOT ENOUGH"),
    ],
)
def test_the_verdict(repro, baseline, released, label):
    assert repro.verdict({"baseline": baseline, "released": released})[0] == label


def test_one_variant_gives_no_verdict(repro):
    assert repro.verdict({"released": _variant(0)})[0] == "INCOMPLETE"


def test_the_summary_counts_crashes_on_every_fork(repro):
    records = [
        {"variant": "baseline", "execs": [{"outcome": "crash"}, {"outcome": "ok"}]},
        {"variant": "baseline", "execs": [{"outcome": "ok"}, {"outcome": "crash"}]},
        {"variant": "released", "execs": [{"outcome": "ok"}, {"outcome": "ok"}]},
    ]
    summary = repro.summarize(records, ["baseline", "released"])
    assert (summary["baseline"]["crashes"], summary["baseline"]["runs"]) == (2, 4)
    assert summary["released"]["crashes"] == 0


def test_the_baseline_really_skips_the_release(repro):
    """A rename would leave baseline identical to released, and the loop would
    report "not reproduced" for the wrong reason."""
    assert callable(zygote._release_import_time_duckdb)
    assert ("zygote._release_import_time_duckdb = lambda: None"
            in repro._BASELINE_ENTRY)


@pytest.mark.parametrize(
    "value, cpus, expected",
    [("0", 64, 0), ("3", 64, 3), ("auto", 4, 2), ("auto", 64, 8), ("auto", 1, 1)],
)
def test_load_resolves_auto_to_half_the_cpus_capped(repro, value, cpus, expected):
    assert repro.resolve_load(value, cpus) == expected


def test_the_string_node_is_the_crashing_e2e_node(repro):
    code = repro.node_code("string")
    assert '"A", "B", "C"' in code  # the string column the e2e node returns
    assert all(line.startswith("    ") for line in code.splitlines() if line)


def test_the_int_node_matches_the_unit_test(repro):
    assert "pd.DataFrame({'a': [1, 2, 3]})" in repro.node_code("int")
