#!/usr/bin/env python3
"""Print the machine-derivable half of a prompt fixture (memo dev/121).

An authoring aid, not a generator: it computes the ``source`` digest, the
declared ``required`` dependencies, and the canonical ``expected`` graph of a
shipped example, so a person writes the PROMPT beside a correct answer key
instead of transcribing one by hand. It writes nothing, and no test calls it --
tests read the committed fixtures and recompute these blocks themselves, which
is what makes a stale fixture a failure.

    python scripts/example_fixture_skeleton.py docs/examples/01-*.json
    python scripts/example_fixture_skeleton.py --all > /tmp/skeletons.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.agents.evaluation.canonical import (  # noqa: E402
    TemplateFacts,
    canonical_graph_from_spec,
)
from utk_curio.backend.app.agents.evaluation.dependencies import (  # noqa: E402
    declared_dependencies,
    referenced_sources,
)
from utk_curio.backend.app.agents.evaluation.fixtures import (  # noqa: E402
    example_paths,
    fixture_id_for_example,
    sha256_of_file,
)


def template_index(packages_root: Path | None = None) -> dict:
    """Manifest facts for every template in the checkout's package catalog.

    The same index the schema suite builds from ``packages/*/manifest.json``
    (``test_trill_schema.py::_template_index``) -- read straight from the
    manifests so no second table of node kinds exists anywhere.
    """
    root = packages_root or (REPO_ROOT / "packages")
    index: dict = {}
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package_id = str(manifest.get("id") or "")
        for template in manifest.get("templates") or []:
            template_id = str(template.get("id") or "")
            if not package_id or not template_id:
                continue
            index[f"{package_id}/{template_id}"] = TemplateFacts(
                template_id=template_id,
                category=str(template.get("category") or "computation"),
                engine=str(template.get("engine") or "python"),
                editor=str(template.get("editor") or "code"),
                has_code=bool(template.get("hasCode")),
                has_grammar=bool(template.get("hasGrammar")),
                behavior=template.get("behavior"),
                backend_handler=template.get("backendHandler"),
            )
    return index


def skeleton(example_path: Path, templates: dict) -> dict:
    spec = json.loads(example_path.read_text(encoding="utf-8"))
    sources = referenced_sources(spec, templates=templates)
    graph = canonical_graph_from_spec(spec, templates=templates, sources=sources)
    deps = declared_dependencies(spec)
    walkthrough = example_path.with_suffix(".md")
    relative = example_path.relative_to(REPO_ROOT).as_posix()
    return {
        "fixtureId": fixture_id_for_example(example_path),
        "version": 1,
        "source": {
            "path": relative,
            "sha256": sha256_of_file(example_path),
            "walkthrough": walkthrough.relative_to(REPO_ROOT).as_posix()
            if walkthrough.exists()
            else None,
        },
        "required": {
            **deps.as_required_dict(),
            **({"paths": list(sources.paths)} if sources.paths else {}),
        },
        "expected": graph.as_expected_dict(),
        "_derived": {
            "undeclaredPackages": list(deps.undeclared_packages),
            "impliedPackages": list(deps.implied_packages),
            "interactionEdges": len(graph.interaction_edges()),
            "executableNodes": sum(1 for n in graph.nodes if n.executable),
            "nodeCount": len(graph.nodes),
            "edgeCount": len(graph.edges),
        },
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("examples", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="every shipped example")
    args = parser.parse_args(argv)
    paths = example_paths() if args.all else [Path(p).resolve() for p in args.examples]
    if not paths:
        parser.error("name an example, or pass --all")
    templates = template_index()
    out = [skeleton(p, templates) for p in paths]
    print(json.dumps(out if len(out) > 1 else out[0], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
