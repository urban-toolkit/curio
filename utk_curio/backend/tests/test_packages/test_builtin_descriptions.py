"""Every built-in node kind documents itself (#225).

The node header offers an info button only for a kind whose descriptor carries
a ``description`` (``hasNodeDescription``), and that description comes straight
from the package manifest. So a built-in kind with an empty description is a
node that silently has no help -- which is the state Spatial Join was reported
in, except that its text existed and merely had no way to be opened.

Asserted on the manifest rather than in the UI because that is where the gap
would appear: adding a template is a manifest edit, and nothing else would fail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILTIN_MANIFEST = REPO_ROOT / "packages" / "curio.builtin@1" / "manifest.json"


def _templates() -> list[dict]:
    manifest = json.loads(BUILTIN_MANIFEST.read_text(encoding="utf-8"))
    return manifest["templates"]


def test_the_builtin_manifest_is_where_we_think_it_is():
    # Guards the path arithmetic above: a missing file would otherwise make
    # every parametrised case below vanish rather than fail.
    assert BUILTIN_MANIFEST.is_file(), BUILTIN_MANIFEST


@pytest.mark.parametrize("template", _templates(), ids=lambda t: t["id"])
def test_every_builtin_template_has_a_description(template):
    description = template.get("description")
    assert isinstance(description, str) and description.strip(), (
        f"{template['id']} has no description, so its info button cannot appear "
        f"and the node ships with no in-product help"
    )


def test_spatial_join_says_what_each_port_expects():
    """The kind #225 was reported against, and what the report asked for.

    Not a spelling check -- the point is that the text answers the three
    questions the issue lists: what each input is, which way the join runs, and
    what comes out.
    """
    spatial_join = next(t for t in _templates() if t["id"] == "spatial-join")
    text = spatial_join["description"].lower()

    assert "points" in text and "polygons" in text, "does not name the two inputs"
    assert "top" in text and "bottom" in text, "does not say which handle is which"
    assert "output" in text, "does not say what the node produces"
    # #262: the property is chosen on the node; the "rename it upstream"
    # workaround is no longer the documented design.
    assert "property" in text, "does not say the tag property is configurable"
    assert "rename" not in text, "still tells the user to rename the field upstream"
