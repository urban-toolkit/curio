"""Do the example JSONs, their walkthroughs, and docs/README.md agree?

#148 ("some dataflows shown in the examples is different than the ones in the
json files") turned out to be four separate disagreements, all pointing the same
way: the JSON is what actually executes and what the e2e matrix runs, so
everything else has to match it.

  1. ``seed_example_projects`` derived each project's title from the *filename*
     and stamped it over the spec's own ``dataflow.name``, on the strength of a
     comment claiming the examples carry no name. All eleven do. The gallery
     showed "Vega lite chained transforms" and, worst of all, "Street vision cv
     analysis" for the example the JSON and the docs both call "Street-level
     computer vision".
  2. Five examples had no ``dataflow.description`` at all, so their gallery cards
     were blank even though README has a blurb for all eleven.
  3. Three mermaid pipeline diagrams drew a different graph than their JSON
     (04 duplicated a shared node, 09 drew one Merge Flow where there are two,
     10 omitted a Data Transformation node).
  4. Markdown code blocks had drifted from the node bodies they document.

Deliberately *semantic* rather than textual, for (4): the walkthroughs
hand-condense JSON specs for readability (``"data": {"name": "table"}`` on one
line) and quote partial fragments under headings like "## Compute". Comparing
text would either force machine-formatted dumps into the docs or force the test
to be skipped. Comparing parsed structures lets the prose stay readable while
still catching a block that says something the node does not.

Pure Python - no browser, no server. Companion to ``test_examples.py``, which
covers node/edge counts.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_example_docs_parity.py -v
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import textwrap

import pytest

from .utils import REPO_ROOT

EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")
README = os.path.join(REPO_ROOT, "docs", "README.md")


def _example_stems() -> list[str]:
    paths = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "[0-9][0-9]-*.json")))
    return [os.path.basename(p)[:-5] for p in paths]


STEMS = _example_stems()


def _dataflow(stem: str) -> dict:
    with open(os.path.join(EXAMPLES_DIR, f"{stem}.json"), encoding="utf-8") as fh:
        return json.load(fh)["dataflow"]


def _markdown(stem: str) -> str:
    with open(os.path.join(EXAMPLES_DIR, f"{stem}.md"), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1 + 2. Titles and descriptions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", STEMS, ids=STEMS)
def test_every_example_declares_a_name_and_description(stem: str):
    """Both fields feed the gallery card, so a missing one is a blank card.

    ``seed_example_projects`` uses ``dataflow.name`` as the project title and
    ``dataflow.description`` as its subtitle.
    """
    dataflow = _dataflow(stem)
    assert (dataflow.get("name") or "").strip(), (
        f"{stem}.json has no dataflow.name, so the gallery falls back to a "
        f"filename-derived title (#148)"
    )
    assert (dataflow.get("description") or "").strip(), (
        f"{stem}.json has no dataflow.description, so its gallery card renders "
        f"with no subtitle (#148)"
    )


@pytest.mark.parametrize("stem", STEMS, ids=STEMS)
def test_the_readme_table_uses_the_same_title_as_the_json(stem: str):
    """Three sources named these examples; they must agree.

    The README row links to ``examples/<stem>.md`` and its link text is the
    title. That text is what a reader compares against the gallery.
    """
    with open(README, encoding="utf-8") as fh:
        readme = fh.read()

    link = f"](examples/{stem}.md)"
    row = next((ln for ln in readme.splitlines() if link in ln), None)
    assert row is not None, f"docs/README.md has no table row linking {stem}.md"

    match = re.search(r"\[([^\]]+)\]\(examples/" + re.escape(stem) + r"\.md\)", row)
    assert match, f"could not read the link text for {stem} out of: {row}"
    assert match.group(1).strip() == (_dataflow(stem).get("name") or "").strip(), (
        f"{stem}: docs/README.md calls it {match.group(1)!r} but the JSON's "
        f"dataflow.name is {_dataflow(stem).get('name')!r}"
    )


# ---------------------------------------------------------------------------
# 3. Mermaid diagrams
# ---------------------------------------------------------------------------

#: Mermaid node declarations: ``ID[label]``, ``ID(label)``, ``ID{label}``.
_MERMAID_NODE = re.compile(r"(?<![\w])([A-Za-z][A-Za-z0-9_]*)\s*[\[({]")

#: Examples whose diagram intentionally does not map 1:1 onto JSON nodes.
_DIAGRAM_EXEMPT = {
    # A single autk-grammar node owns data + compute + map + plot sections; the
    # diagram draws those sections, which is the useful picture even though it
    # outnumbers the nodes.
    "06-autark-what-if-shadow-study",
    "07-autark-gpu-shader",
    "11-autark-pbf-loading",
    "08-autark-spatial-join-regression",
}


@pytest.mark.parametrize(
    "stem", [s for s in STEMS if s not in _DIAGRAM_EXEMPT],
    ids=[s for s in STEMS if s not in _DIAGRAM_EXEMPT],
)
def test_the_mermaid_diagram_draws_as_many_nodes_as_the_json_has(stem: str):
    """A diagram that shows a different graph is the most literal reading of #148.

    Counting rather than matching shapes: it caught all three real cases (04 drew
    a shared node twice, 09 collapsed two Merge Flows into one, 10 dropped a
    Data Transformation) without needing to model mermaid's syntax.
    """
    md = _markdown(stem)
    block = re.search(r"```mermaid\n(.*?)```", md, re.S)
    assert block, f"{stem}.md has no mermaid pipeline diagram"

    body = block.group(1)
    # Strip comments and edge labels so `-. Interaction .->` cannot look like a node.
    body = re.sub(r"^\s*%%.*$", "", body, flags=re.M)
    declared = {
        m.group(1) for m in _MERMAID_NODE.finditer(body)
        if m.group(1) not in {"flowchart", "graph", "subgraph", "end"}
    }
    expected = len(_dataflow(stem)["nodes"])
    assert len(declared) == expected, (
        f"{stem}: the diagram declares {len(declared)} nodes "
        f"({sorted(declared)}) but the JSON has {expected}"
    )


# ---------------------------------------------------------------------------
# 4. Code blocks
# ---------------------------------------------------------------------------

def _parse_json_loose(text: str):
    """Parse a block that may be a fragment such as ``"data": [...]``."""
    for candidate in (text, "{" + text + "}", "{" + text.rstrip().rstrip(",") + "}"):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


#: The walkthroughs' elision convention: a value written as ``... prose ...``
#: stands in for something too long to quote. Example 07's WGSL shader is 4.5 KB,
#: and 06 explicitly writes "see Example 7 for the full body". Recognising this
#: is what lets the check stay strict about everything else.
_ELISION = re.compile(r"^\s*\.\.\..*\.\.\.\s*$", re.S)


def _is_elision(value) -> bool:
    return isinstance(value, str) and bool(_ELISION.match(value))


def _is_subset(small, big) -> bool:
    """True when *small* is structurally contained in *big*.

    The walkthroughs quote excerpts, so containment - not equality - is the
    contract: everything the docs claim must be true of the node, but the docs
    need not repeat all of it.
    """
    if _is_elision(small):
        return True
    if isinstance(small, dict) and isinstance(big, dict):
        return all(k in big and _is_subset(v, big[k]) for k, v in small.items())
    if isinstance(small, list) and isinstance(big, list):
        if len(small) > len(big):
            return False
        return all(any(_is_subset(s, b) for b in big) for s in small)
    return small == big


def _py_equivalent(a: str, b: str) -> bool:
    """Compare Python by AST, so comments and layout do not count as drift."""
    try:
        return ast.dump(ast.parse(textwrap.dedent(a))) == ast.dump(
            ast.parse(textwrap.dedent(b))
        )
    except SyntaxError:
        return False


def _code_blocks(md: str):
    for match in re.finditer(r"```(python|json)\n(.*?)```", md, re.S):
        heading = ""
        headings = re.findall(r"^#{2,3} .*$", md[: match.start()], re.M)
        if headings:
            heading = headings[-1]
        yield heading, match.group(1), match.group(2)


@pytest.mark.parametrize("stem", STEMS, ids=STEMS)
def test_markdown_code_blocks_do_not_contradict_the_nodes(stem: str):
    """Every documented block must be satisfied by some node in the JSON.

    A JSON block has to be a structural subset of a node's spec; a Python block
    has to be AST-equal to a node's body. Both allow the docs to condense and
    excerpt, and neither allows them to state something untrue - which is what
    ``02``'s walkthrough did when it documented zoom/pan and shift-click
    selection ``params`` that its nodes never had.
    """
    contents = [(n.get("content") or "") for n in _dataflow(stem)["nodes"]]
    offenders = []

    for heading, lang, block in _code_blocks(_markdown(stem)):
        if not block.strip():
            continue
        if lang == "json":
            parsed = _parse_json_loose(block)
            if parsed is None:
                # Not JSON at all (an output sample with an `...` elision, say).
                continue
            ok = any(
                (node_parsed := _parse_json_loose(c)) is not None
                and _is_subset(parsed, node_parsed)
                for c in contents
            )
        else:
            try:
                ast.parse(textwrap.dedent(block))
            except SyntaxError:
                # An illustrative snippet, not runnable node code.
                continue
            ok = any(_py_equivalent(block, c) for c in contents)
        if not ok:
            offenders.append(f"{lang} block under {heading.strip() or '(no heading)'}")

    assert not offenders, (
        f"{stem}.md documents code that no node in {stem}.json matches:\n  "
        + "\n  ".join(offenders)
        + "\nThe JSON is the source of truth - it is what runs and what the e2e "
          "matrix executes - so update the walkthrough to match it."
    )
