"""Every example file is named in lowercase words joined by dashes.

The numbered gallery always was (``01-vega-lite-chained-transforms.json``). The
test dataflows beside it in ``dataflows/`` were named with capitals and
underscores; now one rule names every file in both folders.
"""
from __future__ import annotations

import re

import pytest

from utk_curio.backend.app.projects.shipped import TESTS_SUBDIR, examples_dir

#: Words of lowercase letters and digits joined by single dashes, then the extension.
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+")

#: Fewer dataflows than this in a folder means the test read the wrong folder.
SOME_DATAFLOWS = 20


def _file_names(folder) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


@pytest.mark.parametrize("subdir", ["", TESTS_SUBDIR], ids=["examples", "dataflows"])
def test_every_example_file_is_named_in_lowercase_words_joined_by_dashes(subdir):
    names = _file_names(examples_dir() / subdir)
    assert len([n for n in names if n.endswith(".json")]) >= SOME_DATAFLOWS, names
    misnamed = [n for n in names if not NAME.fullmatch(n)]
    assert not misnamed, f"not named in lowercase words joined by dashes: {misnamed}"


def test_the_rule_refuses_capitals_underscores_and_stray_dashes():
    for good in ("06-a-study.json", "data-pool-chart-2.json", "a-notebook.ipynb", "07-a-study.md"):
        assert NAME.fullmatch(good), good
    for bad in ("DataPoolChart.json", "data_pool.json", "a_notebook.ipynb", "two--dashes.json",
                "-leading.md", "trailing-.json", "no-extension"):
        assert not NAME.fullmatch(bad), bad
