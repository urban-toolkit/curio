"""Every example dataflow and walkthrough is named in lowercase words joined by dashes.

The numbered gallery always was (``01-vega-lite-chained-transforms.json``). The
test dataflows beside it in ``dataflows/`` were named with capitals and
underscores; now one rule names the dataflows (``.json``) and walkthroughs
(``.md``) in both folders. Other files there keep their names: the notebook the
tours import stays ``test_notebook.ipynb``.
"""
from __future__ import annotations

import re

import pytest

from utk_curio.backend.app.projects.shipped import TESTS_SUBDIR, examples_dir

#: The files the rule names: dataflows and their walkthroughs.
NAMED = (".json", ".md")

#: Words of lowercase letters and digits joined by single dashes, then the extension.
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+")

#: Fewer dataflows than this in a folder means the test read the wrong folder.
SOME_DATAFLOWS = 20


def _named_files(folder) -> list[str]:
    """The dataflows and walkthroughs in *folder*, whatever case their extension is in."""
    return sorted(p.name for p in folder.iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in NAMED)


@pytest.mark.parametrize("subdir", ["", TESTS_SUBDIR], ids=["examples", "dataflows"])
def test_every_dataflow_and_walkthrough_is_named_in_lowercase_words_joined_by_dashes(subdir):
    names = _named_files(examples_dir() / subdir)
    assert len([n for n in names if n.endswith(".json")]) >= SOME_DATAFLOWS, names
    misnamed = [n for n in names if not NAME.fullmatch(n)]
    assert not misnamed, f"not named in lowercase words joined by dashes: {misnamed}"


def test_the_rule_refuses_capitals_underscores_and_stray_dashes():
    for good in ("06-a-study.json", "data-pool-chart-2.json", "a-walkthrough.md", "07-a-study.md"):
        assert NAME.fullmatch(good), good
    for bad in ("DataPoolChart.json", "data_pool.json", "a_walkthrough.md", "two--dashes.json",
                "-leading.md", "trailing-.json", "no-extension", "Upper.JSON"):
        assert not NAME.fullmatch(bad), bad
