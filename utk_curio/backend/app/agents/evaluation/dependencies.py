"""Dependency and source extraction for the validation harness (memo dev/121).

Two questions, both answered from the production paths rather than a second
scanner:

*What does the dataflow DECLARE?* ``dataflow.datasets`` (the backend-owned refs
of dev/81) and ``dataflow.packages`` (the lockfile authority of dev/101) are
the dependency source of truth. Declared package dirNames are additionally
derived from the node types present, through
``spec_packages.dir_name_from_node_type``, so a graph using a package template
without declaring it is visible as an undeclared dependency rather than a
silent pass.

*What does the code actually READ?* ``source_grounding.scan_sources`` -- the
same scanner the ``DEC-072`` gate runs before any agent-authored content may
become a proposal or be written by Solve. Its verdicts (``catalog-id``,
``path``, ``url``) are the fabrication baseline: a reconstructed node that
opens something outside the fixture's declared sources has invented a
resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from utk_curio.backend.app.agents import source_grounding
from utk_curio.backend.app.agents.evaluation.canonical import Sources, TemplateIndex
from utk_curio.backend.app.packages.services import canonical_template_id
from utk_curio.backend.app.packages.spec_packages import dir_name_from_node_type


@dataclass(frozen=True)
class Dependencies:
    """What a dataflow declares, and what its node types imply."""

    datasets: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    #: dirNames implied by the node types present (builtin included).
    implied_packages: tuple[str, ...] = ()
    #: Implied but not declared -- an unresolved dependency by construction.
    undeclared_packages: tuple[str, ...] = ()

    def as_required_dict(self, *, drop_builtin: bool = True) -> dict:
        packages = [
            dn for dn in self.packages
            if not (drop_builtin and dn.startswith("curio.builtin@"))
        ]
        return {"datasets": list(self.datasets), "packages": packages}


def _dataflow(spec: Mapping) -> Mapping:
    inner = spec.get("dataflow")
    return inner if isinstance(inner, Mapping) else spec


def declared_dependencies(
    spec: Mapping,
    *,
    installed_majors_by_pkg: Mapping | None = None,
) -> Dependencies:
    """The dataflow's declared datasets and packages, plus what its node types
    imply.

    ``installed_majors_by_pkg`` is the resolver hint
    ``dir_name_from_node_type`` takes for an unversioned type; when it is
    absent, an unversioned type whose package major cannot be derived is
    reported through the declared list only (never guessed).
    """
    dataflow = _dataflow(spec)
    datasets = sorted(
        {
            str(ref.get("datasetId"))
            for ref in (dataflow.get("datasets") or [])
            if isinstance(ref, Mapping) and ref.get("datasetId")
        }
    )
    declared = sorted(
        {str(e) for e in (dataflow.get("packages") or []) if isinstance(e, str) and e.strip()}
    )

    hint = dict(installed_majors_by_pkg or {})
    if not hint:
        # Every package in the corpus ships at major 1; the declared list is
        # the authority when it names one, so this hint only fills the gap for
        # an unversioned type in a spec that declared nothing.
        for dir_name in declared:
            package_id, _, major = dir_name.partition("@")
            if major.isdigit():
                hint.setdefault(package_id, []).append(int(major))
        hint.setdefault("curio.builtin", [1])

    implied: set = set()
    for node in dataflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        canonical = canonical_template_id(node.get("type"))
        if not canonical or "/" not in canonical:
            continue
        dir_name = dir_name_from_node_type(canonical, hint)
        if dir_name:
            implied.add(dir_name)

    undeclared = sorted(
        dn for dn in implied
        if dn not in set(declared) and not dn.startswith("curio.builtin@")
    )
    return Dependencies(
        datasets=tuple(datasets),
        packages=tuple(declared),
        implied_packages=tuple(sorted(implied)),
        undeclared_packages=tuple(undeclared),
    )


def referenced_sources(
    spec: Mapping,
    *,
    templates: TemplateIndex | None = None,
) -> Sources:
    """Every source the graph's node code reads, via the ``DEC-072`` scanner.

    The engine passed to the scanner is the node template's own (``python`` by
    default), so a JavaScript node's literals are read by the regex fallback
    rather than mis-parsed as python -- the same choice the gate makes.
    """
    dataflow = _dataflow(spec)
    dataset_ids: set = set()
    paths: set = set()
    urls: set = set()
    index = templates or {}
    for node in dataflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        content = node.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        facts = index.get(canonical_template_id(node.get("type")))
        engine = getattr(facts, "engine", None) or "python"
        for ref in source_grounding.scan_sources(content, engine):
            if ref.kind == "catalog-id":
                dataset_ids.add(ref.literal)
            elif ref.kind == "url":
                urls.add(ref.literal)
            elif ref.kind == "path":
                paths.add(ref.literal)
    return Sources(
        dataset_ids=tuple(sorted(dataset_ids)),
        paths=tuple(sorted(paths)),
        urls=tuple(sorted(urls)),
    )


def url_allowed(url: str, allowlist: Iterable) -> bool:
    """Whether *url* matches one of the fixture's allowed prefixes.

    Prefix matching, not host matching: a fixture that allows
    ``https://vega.github.io/schema/`` is not allowing the rest of the host.
    """
    text = str(url or "")
    return any(text.startswith(str(prefix)) for prefix in allowlist)
