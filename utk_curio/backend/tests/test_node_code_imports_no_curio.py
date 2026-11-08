"""Node code imports nothing from Curio's own code.

A node's logic is its code (docs/EXTENDING.md, "A node's logic is its code"):
what a package's node runs is in the package's sources, and what Curio gives
node code is the functions skills/node-functions/SKILL.md lists, which need no
import. So no package source, and no node of a shipped example, imports from
``utk_curio``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: An import of Curio's code: a line that starts, after its indent, with
#: ``from utk_curio`` or ``import utk_curio``.
CURIO_IMPORT = re.compile(r"^[ \t]*(?:from|import)[ \t]+utk_curio\b", re.MULTILINE)

#: The folders of the shipped examples' dataflows, from the repository root.
EXAMPLE_FOLDERS = ("docs/examples", "docs/examples/dataflows")


def _contents(value):
    """Every string a dataflow holds under a ``content`` key, at any depth: the
    code of each of its nodes."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "content" and isinstance(item, str):
                yield item
            else:
                yield from _contents(item)
    elif isinstance(value, list):
        for item in value:
            yield from _contents(item)


def node_code(repo: Path):
    """``(where, code)`` for each package source and each shipped example."""
    for path in sorted((repo / "packages").glob("*/sources/**/*.py")):
        yield path.relative_to(repo).as_posix(), path.read_text(encoding="utf-8")
    for folder in EXAMPLE_FOLDERS:
        for path in sorted((repo / folder).glob("*.json")):
            where = path.relative_to(repo).as_posix()
            dataflow = json.loads(path.read_text(encoding="utf-8"))
            yield where, "\n".join(_contents(dataflow))


def importers(repo: Path) -> set[str]:
    """The files whose node code imports Curio's code."""
    return {where for where, code in node_code(repo) if CURIO_IMPORT.search(code)}


def test_the_scan_reads_package_sources_and_examples():
    wheres = [where for where, _code in node_code(REPO)]
    assert "packages/curio.media@1/sources/video-frames.py" in wheres
    assert "docs/examples/10-street-vision-cv-analysis.json" in wheres
    assert any(where.startswith("docs/examples/dataflows/") for where in wheres)


def test_the_scan_finds_imports_planted_in_node_code(tmp_path):
    sources = tmp_path / "packages" / "me.planted@1" / "sources" / "helpers"
    sources.mkdir(parents=True)
    (sources / "steps.py").write_text(
        "def step(value):\n    from utk_curio.sandbox.util import rasters\n    return value\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "examples" / "dataflows").mkdir(parents=True)
    node = {"id": "n", "content": "import utk_curio.sandbox.util.rasters\nreturn input_0\n"}
    (tmp_path / "docs" / "examples" / "planted.json").write_text(
        json.dumps({"dataflow": {"nodes": [node]}}), encoding="utf-8"
    )
    clean = {"id": "m", "content": "# from utk_curio nothing here\nreturn input_0\n"}
    (tmp_path / "docs" / "examples" / "dataflows" / "clean.json").write_text(
        json.dumps({"dataflow": {"nodes": [clean]}}), encoding="utf-8"
    )
    assert importers(tmp_path) == {
        "packages/me.planted@1/sources/helpers/steps.py",
        "docs/examples/planted.json",
    }


def test_no_node_code_imports_curio():
    unexpected = sorted(importers(REPO))
    assert not unexpected, (
        "node code imports Curio's code: " + ", ".join(unexpected) + ". A node's logic is its code: put it in the "
        "node's source or a module of its package, and call only the functions skills/node-functions/SKILL.md lists."
    )
