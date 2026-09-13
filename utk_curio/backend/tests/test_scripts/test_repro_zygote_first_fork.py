"""Does ``scripts/repro_zygote_first_fork.py`` draw the right conclusion?

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
SCRIPT = os.path.join(REPO_ROOT, "scripts", "repro_zygote_first_fork.py")


@pytest.fixture(scope="module")
def repro():
    spec = importlib.util.spec_from_file_location("repro_zygote_first_fork", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _variant(first_crashes, runs=300, later_crashes=0):
    return {
        "first_fork": {"crash": first_crashes, "ok": runs - first_crashes},
        "later_forks": {"crash": later_crashes, "ok": runs - later_crashes},
        "first_fork_runs": runs,
        "later_fork_runs": runs,
    }


def test_the_fisher_test_reproduces_the_ci_numbers(repro):
    # 2 of 36 first forks crashed in CI, 0 of ~252 later ones.
    assert repro.one_sided_fisher(2, 36, 0, 252) == pytest.approx(0.0152, abs=1e-4)


def test_no_crashes_is_no_evidence(repro):
    assert repro.one_sided_fisher(0, 300, 0, 300) == 1.0


@pytest.mark.parametrize(
    "baseline, warmup, label",
    [
        (_variant(10), _variant(0), "SUPPORTED"),
        (_variant(2), _variant(0), "SUGGESTIVE"),
        (_variant(0), _variant(0), "NOT REPRODUCED"),
        (_variant(9), _variant(3), "NOT ENOUGH"),
        (_variant(9), _variant(0, later_crashes=1), "NOT ENOUGH"),
    ],
)
def test_the_verdict(repro, baseline, warmup, label):
    assert repro.verdict({"baseline": baseline, "warmup": warmup})[0] == label


def test_one_variant_gives_no_verdict(repro):
    assert repro.verdict({"warmup": _variant(0)})[0] == "INCOMPLETE"


def test_the_baseline_really_disables_the_warmup_fork(repro):
    """A rename would leave baseline identical to warmup, and the loop would
    report "not reproduced" for the wrong reason."""
    assert callable(zygote._settle_before_serving)
    assert "zygote._settle_before_serving = lambda: None" in repro._BASELINE_ENTRY


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
