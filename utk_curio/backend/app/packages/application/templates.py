"""The node-template roster: canonical ids, the ONE availability gate, the rows every listing returns, content kinds and executability (memos dev/48, dev/93, dev/119, dev/134). The single source of template knowledge (ADR-AG-007).

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import re

from utk_curio.backend.app.packages.domain.manifest import parse_cardinality
from utk_curio.backend.app.packages.application import (
    project_packages as packages_project_packages,
    store_reads as packages_store_reads,
)
from utk_curio.backend.app.packages.application.seeding import BUILTIN_PACKAGE_ID

log = logging.getLogger(__name__)


# DEC-051 (dev/67-3): where a template's DECLARED cardinality and its RENDERED
# input capacity disagree, the rendered capacity is the enforceable truth —
# merge-flow declares one "[1,n]" port but the canvas renders exactly 5 slots
# (mergeFlowBehavior MERGE_SLOT_COUNT), so 5 is what a graph can actually hold.
_RENDERED_INPUT_CAPACITY: dict[str, int] = {"curio.builtin/merge-flow": 5}


def input_capacity(canonical: str, port_count: int, cardinality: str | None = None) -> int | None:
    """How many incoming edges a node of this template accepts, or None for
    any number. A template with one input port takes its declared upper bound
    (*cardinality*): the canvas draws a new circle for each edge, up to it.
    Several ports are named circles, one edge each. Merge Flow renders its own
    slots (DEC-051). The one rule ``maxIncomingEdges`` and the agents' preamble
    both read, and the canvas's ``maxInputs`` follows."""
    if canonical in _RENDERED_INPUT_CAPACITY:
        return _RENDERED_INPUT_CAPACITY[canonical]
    if port_count == 1 and cardinality is not None:
        return parse_cardinality(cardinality)[1]
    return port_count


def _input_arity(canonical: str, template) -> tuple[list[dict], int | None]:
    """Per-port ``{types, min, max}`` rows + the template's incoming-edge
    capacity (``input_capacity``): one port's declared maximum, one edge per
    port when there are several.
    """
    inputs: list[dict] = []
    for port in template.input_ports:
        lo, hi = parse_cardinality(port.cardinality)
        inputs.append({"types": list(port.types), "min": lo, "max": hi})
    single = template.input_ports[0].cardinality if len(template.input_ports) == 1 else None
    return inputs, input_capacity(canonical, len(inputs), single)


# One value, three legal spellings (memo dev/93 D3; the dev/90 A14 family).
# The canonical form is UNVERSIONED ``<packageId>/<templateId>`` — what
# ``available_templates`` returns and what a spec pins — but the ecosystem
# hands models the other two constantly: the client registry keys descriptors
# VERSIONED (``<packageId>/<templateId>@<major>``, so the run context, the
# canvas graph, and the runtime's own proposal previews all speak it), and
# legacy trill files carry the pre-package ENUM names (``DATA_LOADING``).
# A model quoting an id from its own context must never be refused for
# quoting it in a spelling the system itself produced.
_VERSIONED_TEMPLATE_RE = re.compile(r"^(?P<base>.+/.+)@(?P<major>0|[1-9][0-9]{0,3})$")


_LEGACY_ENUM_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def canonical_template_id(node_type: object) -> str:
    """Any legal spelling of a node type → the canonical unversioned id.

    Shape only: no filesystem access, no availability check — availability is
    :func:`resolve_template`'s job, and keeping this pure lets it run at the
    parse boundary where a plan is first read.

    The legacy enum names are DERIVED rather than tabulated: every member of
    the frontend's ``NodeType`` enum is its template id upper-snake-cased
    (``DATA_LOADING`` ↔ ``curio.builtin/data-loading``), so the rule cannot
    drift out of sync with a hand-maintained list the way a table would, and
    it covers built-in templates that never got an enum member (spatial-join)
    for free. A bogus ALL-CAPS token maps to a canonical id that simply is not
    available, which refuses with the ordinary message.

    Anything unrecognised is returned unchanged — including a bare
    ``data-loading`` with no package id, which stays ambiguous on purpose, and
    a case variant, since template ids are case-sensitive by contract.
    """
    if not isinstance(node_type, str):
        return ""
    text = node_type.strip()
    if not text:
        return ""
    versioned = _VERSIONED_TEMPLATE_RE.match(text)
    if versioned:
        return versioned.group("base")
    if "/" not in text and _LEGACY_ENUM_RE.match(text):
        return f"{BUILTIN_PACKAGE_ID}/{text.lower().replace('_', '-')}"
    return text


def resolve_template(
    user_key: str,
    project_id: str,
    node_type: object,
    *,
    require_authorable: bool = False,
) -> tuple[dict | None, str]:
    """The ONE availability gate for a node type (memo dev/93 D3).

    Accepts every spelling :func:`canonical_template_id` knows and returns
    ``(entry | None, error_text)``, where ``entry`` is the
    :func:`available_templates` row — so the caller pins the canonical id, not
    whatever the model typed. Plans and ``node.create`` share this so they can
    no longer disagree about what a template id is: before this, a plan naming
    ``curio.builtin/data-loading@1`` was refused while ``node.create`` accepted
    the very same string, and the model — quoting an id its own prompt had
    given it — had no way to tell which spelling any given tool wanted.

    ``require_authorable`` is the one intended difference between the callers
    and is therefore explicit at both: ``node.create`` writes content, so it
    needs a template that holds authored content; a PLAN places a typed
    placeholder whose content arrives later from Solve, so it does not.

    A degraded registry is reported as such rather than blamed on the id: an
    unreadable package store used to surface as "that template is not
    available", which is how a corrupted install (dev/93 D1) reached a model
    as its own mistake.
    """
    return resolve_templates(
        user_key, project_id, [node_type], require_authorable=require_authorable,
    )[0]


def resolve_templates(
    user_key: str,
    project_id: str,
    node_types: list,
    *,
    require_authorable: bool = False,
) -> list[tuple[dict | None, str]]:
    """:func:`resolve_template` for many node types against ONE snapshot
    (memo dev/99 R1.2).

    Returns ``(entry | None, error_text)`` per input, positionally. The point
    is the snapshot, not the batching: a plan mint resolves every node it
    proposes, so resolving them one at a time re-walked the package store —
    and once readers hold the seed lock, re-acquired it — once per node. A
    12-node plan meant 13 walks and 13 acquisitions. Here the store is read
    once however many types are asked about, so the cost stops scaling with
    plan size and every node is judged against the same instant.
    """
    try:
        report = available_templates_report(user_key, project_id)
    except Exception as exc:  # unavailable registry is data, not a run error
        message = f"the node template registry is unavailable: {exc}"
        return [(None, message) for _ in node_types]
    by_id = {t["id"]: t for t in report["templates"]}
    out: list[tuple[dict | None, str]] = []
    for node_type in node_types:
        out.append(
            _resolve_one(node_type, by_id, report["skipped"], require_authorable)
        )
    return out


def _resolve_one(
    node_type: object,
    by_id: dict,
    skipped: list,
    require_authorable: bool,
) -> tuple[dict | None, str]:
    """One resolution against an existing availability snapshot. No I/O."""
    if not isinstance(node_type, str) or not node_type.strip():
        return None, "params.nodeType must be a non-empty template id string"
    entry = by_id.get(canonical_template_id(node_type))
    if entry is None:
        if skipped:
            unreadable = ", ".join(sorted(skipped))
            return None, (
                f"nodeType {node_type!r} is not available AND this project's "
                f"package store is degraded — {unreadable} could not be read, so "
                "templates it provides are missing from the list. Report this "
                "rather than choosing a different template"
            )
        return None, (
            f"nodeType {node_type!r} is not an available template for this project — "
            "choose an id from the Available node templates list (the versioned "
            "form '<packageId>/<templateId>@<major>' is also accepted)"
        )
    if require_authorable and not entry.get("authorable"):
        return None, (
            f"template {node_type!r} does not hold authored content — choose an "
            "authorable template from the Available node templates list"
        )
    return entry, ""


def _template_entry(package_id: str, template) -> dict:
    """One roster row for a manifest template — the shape every template
    listing in this module returns (memo dev/48; arity per dev/67-3, DEC-051).
    """
    canonical = f"{package_id}/{template.template_id}"
    inputs, max_incoming = _input_arity(canonical, template)
    return {
        "id": canonical,
        "label": template.label,
        "description": template.description,
        "category": template.category,
        # Whether a node of this template can carry an interaction edge: its
        # third, "in/out" handle. plan_topology reads the interaction rule
        # from this and the category.
        "bidirectional": bool(template.bidirectional),
        # dev/90 A14: a PRESENTATION template (editor none + a custom
        # behavior — the dev/89 post-it profile) holds authorable CONTENT
        # (the note text its behavior renders) even though it has no code
        # editor; without this, reuse-first note creation was impossible by
        # construction (node.create refused every note template).
        "authorable": bool(
            template.has_code or template.has_grammar
            or (template.behavior and template.editor == "none")
        ),
        # dev/105 S1 (additive): a PRESENTATION template renders content
        # without code — the note profile. The roster tells a note-composing
        # agent when none of the available templates is one, so it never
        # reaches for a code template (or a canvas node's type) to hold a note.
        "presentation": bool(template.behavior and template.editor == "none"),
        # dev/119 (DEC-076): the schema-required facts the runner's
        # executability is derived from — a hand-kept list of legacy names is
        # the drift DEC-062 exists to prevent. ``executable`` is THE derivation:
        # an editable code surface, an engine the sandbox runs, and no package
        # backend handler (dev/91's separate execution path).
        "engine": template.engine,
        "editor": template.editor,
        "hasCode": bool(template.has_code),
        "backendHandler": bool(template.backend_handler),
        "executable": template_is_executable(template),
        # dev/134: what KIND of content this template carries, derived from the
        # same declared facts (never a name list — DEC-076's rule). The write
        # gate reads it: code runs in the sandbox, a grammar is validated as a
        # document, and a wired node has nothing to author at all.
        "hasGrammar": bool(template.has_grammar),
        **({"grammar": template.grammar_id} if template.grammar_id else {}),
        "contentKind": template_content_kind(template),
        "inputs": inputs,
        "maxIncomingEdges": max_incoming,
    }


#: dev/134: the four kinds of content a node template can carry.
CONTENT_KIND_CODE = "code"


CONTENT_KIND_GRAMMAR = "grammar"


CONTENT_KIND_NOTE = "note"


CONTENT_KIND_NONE = "none"


def template_content_kind(template) -> str:
    """What kind of content a node of this template carries (memo dev/134).

    The write gate needs three different things of three different kinds, and
    the manifest already declares which is which — so this is a DERIVATION, in
    one place, rather than a list of node names somewhere in the agents layer
    (``DEC-076``'s rule, the same one ``template_is_executable`` follows):

    - ``code``    — an editable code surface the sandbox runs (``hasCode``);
    - ``grammar`` — an authored DOCUMENT, validated but never executed
      (``hasGrammar``; ``grammarId`` says which grammar);
    - ``none``    — nothing is authored: the node renders or forwards its INPUT
      and everything it does comes from the wiring (``editor: "none"`` with an
      input port, or an explicit ``containerStyle.noContent``). Asking a model
      for this node's content can only produce something wrong;
    - ``note``    — authored presentation content with no validator: dev/90
      A14's post-it profile (``editor: "none"``, NO input port and no widgets).

    A template with ``editor: "none"`` that holds widgets (``hasWidgets``, the
    Parameter node) is set through them, at ``metadata.widgets``: its content
    is ``none``.
    """
    if bool(template.has_code):
        return CONTENT_KIND_CODE
    if bool(template.has_grammar):
        return CONTENT_KIND_GRAMMAR
    if (template.container_style or {}).get("noContent"):
        return CONTENT_KIND_NONE
    if str(template.editor or "") == "none":
        # A presentation template with an input renders THAT (a pool, a merge, a
        # simple view), and one with widgets is set through them; one with
        # neither renders what its author wrote (a note).
        if (template.input_ports or []) or bool(getattr(template, "has_widgets", False)):
            return CONTENT_KIND_NONE
        return CONTENT_KIND_NOTE
    return CONTENT_KIND_NONE


def template_is_executable(template) -> bool:
    """dev/119 (DEC-076): whether the sandbox can RUN a node of this template.
    Derived from the manifest's required fields, never from its name."""
    return bool(
        getattr(template, "has_code", False)
        and getattr(template, "engine", None) in ("python", "javascript")
        and not getattr(template, "backend_handler", None)
    )


def roster_templates(user_key: str, project_id: str) -> dict | None:
    """dev/119: ``{canonical_id: {"executable", "engine"}}`` for every template
    the project can use — the snapshot the runner, the loop and the batch
    classify against. ``None`` when the roster is unreachable (callers fall
    back to the legacy tables)."""
    try:
        return {
            t["id"]: {
                "executable": bool(t.get("executable")),
                "engine": t.get("engine") or "python",
                # dev/134: the write gate's routing rides the same snapshot.
                "contentKind": t.get("contentKind") or "none",
                **({"grammar": t["grammar"]} if t.get("grammar") else {}),
            }
            for t in available_templates(user_key, project_id)
        }
    except Exception:
        return None


def installed_templates_not_in_project(user_key: str, project_id: str) -> list[dict]:
    """Templates the user HAS installed that this project has not enlisted.

    The reuse-first counterpart to :func:`available_templates` (memo dev/93
    D4). Availability is *store ∩ project lockfile*, so a package the user
    already owns is invisible to a project whose lockfile omits it — and an
    agent told to "reuse an installed template" then concludes none exists
    and authors a duplicate package instead. This listing is what makes the
    distinction sayable: these templates exist and are one reviewed
    ``package.install`` away from being usable here.

    Each row is a :func:`_template_entry` plus ``dirName`` — the
    ``<packageId>@<major>`` a ``package.install`` proposal takes. Built-ins
    are excluded (always present, never proposable) and so is anything the
    lockfile already names.
    """
    wanted = packages_project_packages._lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _installed_templates_not_in_project_unlocked(
        wanted, packages_store_reads._locked_store_index(user_key),
    )


def _installed_templates_not_in_project_unlocked(
    wanted: set[str], store: dict[str, object],
) -> list[dict]:
    """:func:`installed_templates_not_in_project` over an existing store
    snapshot (dev/99 R2). Takes no locks and performs no I/O."""
    out: list[dict] = []
    seen: set[str] = set()
    for dir_name in sorted(store):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id == BUILTIN_PACKAGE_ID or dir_name in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            continue
        for t in manifest.templates:
            entry = _template_entry(manifest.package_id, t)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            out.append({**entry, "dirName": dir_name})
    return sorted(out, key=lambda e: e["id"])


def available_templates(user_key: str, project_id: str) -> list[dict]:
    """The node templates a project may instantiate (memo dev/48).

    Scope = the seeded ``curio.builtin@<highest-major>`` store package (always
    present on every canvas) plus every package in the project's package
    lockfile. Each entry is ``{"id", "label", "description", "authorable",
    "inputs", "maxIncomingEdges"}`` (arity per dev/67-3, DEC-051) where
    ``id`` is the canonical UNVERSIONED ``<packageId>/<templateId>``
    node type the canvas stores in ``data.nodeType``. This is the single
    source of template knowledge for agent node creation (`ADR-AG-007`) —
    the agents module owns none of its own. Unreadable packages are skipped
    (they cannot provide working nodes); a project without a spec resolves
    to the builtin templates only.

    See :func:`available_templates_report` when the caller needs to know
    whether anything WAS skipped — silence about that is what let a
    truncated package store reach a model as "that template is not
    available" (memo dev/93 D2).
    """
    return available_templates_report(user_key, project_id)["templates"]


def available_templates_report(user_key: str, project_id: str) -> dict:
    """:func:`available_templates` plus what it could not read.

    ``{"templates": [...], "skipped": [dirName, ...]}``. The skip list exists
    because the bare ``except (ManifestError, OSError): continue`` this
    function is built on is silent by nature: a package whose manifest will
    not load simply vanishes from every roster, so a store that lost its
    built-in manifest looked identical to a project that legitimately has few
    templates — and the refusal three layers away blamed the node type. Each
    skip is also logged at WARNING; an unreadable installed package is an
    abnormal state, not routine.
    """
    wanted = packages_project_packages._lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _available_templates_report_unlocked(wanted, packages_store_reads._locked_store_index(user_key))


def _available_templates_report_unlocked(
    wanted: set[str], store: dict[str, object],
) -> dict:
    """:func:`available_templates_report` over an existing store snapshot
    (dev/99 R2). Takes no locks and performs no I/O.

    The scope filter runs BEFORE the readability check, exactly as before: a
    package outside this project's scope is passed over silently and never
    reported as skipped, so the skip list keeps meaning "in scope for this
    project and unreadable".
    """
    out: list[dict] = []
    seen: set[str] = set()
    skipped: list[str] = []
    # Prefer the highest seeded builtin major when several exist.
    for dir_name in sorted(store, reverse=True):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id != BUILTIN_PACKAGE_ID and dir_name not in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            # Loud, because the consequence is invisible: every template this
            # package provides disappears from the roster (dev/93 D2).
            log.warning(
                "Package %s is installed but unreadable (%s) — its templates are "
                "missing from this project's roster",
                dir_name, manifest,
            )
            skipped.append(dir_name)
            continue
        for t in manifest.templates:
            entry = _template_entry(manifest.package_id, t)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            out.append(entry)
    return {
        "templates": sorted(out, key=lambda e: e["id"]),
        "skipped": sorted(skipped),
    }


def presentation_templates(user_key: str, project_id: str) -> list[dict]:
    """dev/95: the installed+enlisted PRESENTATION templates (a custom
    ``behavior`` + editor ``"none"`` — the dev/90 A14 profile whose content
    IS the note text its behavior renders).

    These are the note-surface candidates the runtime offers a delegated
    Researcher (a DEC-046 child cannot browse the roster itself); the child
    picks one by id and the mint re-validates through the ONE template
    vocabulary. Same enumeration and skip posture as
    :func:`available_templates_report` — an unreadable package stays loud
    there; here it simply contributes no candidates."""
    wanted = packages_project_packages._lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _presentation_templates_unlocked(wanted, packages_store_reads._locked_store_index(user_key))


def _presentation_templates_unlocked(
    wanted: set[str], store: dict[str, object],
) -> list[dict]:
    """:func:`presentation_templates` over an existing store snapshot
    (dev/99 R2). Takes no locks and performs no I/O."""
    out: list[dict] = []
    seen: set[str] = set()
    for dir_name in sorted(store, reverse=True):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id != BUILTIN_PACKAGE_ID and dir_name not in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            continue  # available_templates_report already logs this loudly
        for t in manifest.templates:
            if not (t.behavior and t.editor == "none"):
                continue
            canonical = f"{manifest.package_id}/{t.template_id}"
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append({
                "id": canonical,
                "label": t.label,
                "description": t.description,
            })
    return sorted(out, key=lambda e: e["id"])
