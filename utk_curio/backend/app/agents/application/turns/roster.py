"""Roster and template blocks handed to the model: available, enlistable, executable.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _node_is_executable(node_obj: dict | None, templates: dict | None = None) -> bool:
    """dev/118 (DEC-075) → dev/119 (DEC-076): the ONE executability predicate
    the batch, the per-node Solve and validate-node consult. With the roster
    snapshot the template's own facts decide; without one the legacy tables
    are the fallback."""
    from utk_curio.backend.app.execution.workflow_spec import is_executable_kind

    return is_executable_kind(str((node_obj or {}).get("type") or ""), templates)


def _roster_templates(user_key: str, project_id: str) -> dict | None:
    """dev/119: the roster snapshot for a project, or None when unreachable."""
    from utk_curio.backend.app.packages import service as _pkg

    return _pkg.roster_templates(user_key, project_id)


# Bounds for the run-time template roster (dev/48): plenty for every real
# project, small enough to never crowd the context.
_TEMPLATES_BLOCK_MAX_ENTRIES = 60


_TEMPLATES_BLOCK_DESC_CHARS = 140


# The grants that earn the run-time template roster: putting a template on the
# canvas (node.create), planning one (dataflow.plan.write), enlisting a package
# that provides one (package.install), or authoring a new one
# (package.draft.apply). This set covers every built-in that declares the
# `installedTemplates` read, which is what let dev/93 commit 4 retire the
# duplicate client-composed roster — the one that spelled ids VERSIONED while
# this one spelled them unversioned, and listed palette templates the project
# could not actually instantiate.
_ROSTER_GRANTS = frozenset({
    "node.create", "dataflow.plan.write", "package.install", "package.draft.apply",
})


def _template_line(entry: dict, *, suffix: str = "") -> str:
    desc = (entry.get("description") or "")[:_TEMPLATES_BLOCK_DESC_CHARS]
    return f"- {entry['id']} — {entry['label']}" + (f": {desc}" if desc else "") + suffix


_NO_NOTE_TEMPLATE_LINE = (
    "None of these renders a note (no presentation template is enlisted in this "
    "project): code templates and node types you see on the canvas cannot hold "
    "note content — take the 'Installed but NOT enlisted in this project' rung "
    "(when offered) or delegate authoring; do not node.create on any of the above."
)


def roster_block(templates: list, *, notes_agent: bool = False) -> str | None:
    """The roster listing a run's system turn carries, for a caller outside a run.

    A thin public wrapper over :func:`_available_templates_block`, added by memo
    dev/122 so the training-set builder composes its system turn with the SAME
    formatter a live run uses. Building a training example against a
    hand-written roster paragraph would teach the model a prompt shape the
    runtime never sends — a second vocabulary of exactly the kind ``DEC-062``
    exists to prevent.

    ``templates`` is a roster row list as ``packages_services.available_templates``
    returns it. There is no project here, so the log line's project id reads
    ``"training"``.
    """
    return _available_templates_block(
        "training", {"available": list(templates)}, notes_agent=notes_agent
    )


def _available_templates_block(
    project_id: str, landscape: dict | None, *, notes_agent: bool = False
) -> str | None:
    """The grant-aware node-template listing appended to a node.create or
    dataflow.plan.write run's system content, composed from the
    packages-domain helpers so it is never stale (memo dev/48).

    Two sections, because one bucket could not express the difference that
    matters (memo dev/93 D4). "Available" is what this project can
    instantiate right now. "Installed but not enlisted" is what the user
    already owns and could enlist with one reviewed ``package.install`` —
    without it, a template the user has looks identical to a template that
    does not exist anywhere, and an agent told to reuse concludes "there is
    no installed notes template on your canvas" and authors a duplicate
    package. The second section is offered only to a run that can act on it
    (a ``package.install`` grant); everyone else sees the roster unchanged.
    """
    entries = [t for t in (landscape or {}).get("available", []) if t.get("authorable")]
    shown = entries[:_TEMPLATES_BLOCK_MAX_ENTRIES]
    if len(entries) > len(shown):
        log.warning(
            "Template roster truncated for project %s: %d of %d available "
            "templates listed",
            project_id, len(shown), len(entries),
        )
    if not shown:
        # dev/105 S1: an EMPTY roster is said, not omitted. The live failure:
        # this project's only available template was a Python compute node
        # (not authorable, so filtered out above), the section vanished, and
        # the model reached for the node type it could see on the canvas via
        # dataflow.read — refused, one round spent. Silence read as "no rule
        # here"; the explicit line names the rule and the way out.
        return (
            "Available node templates: none — nothing enlisted in this project "
            "can hold authored content. Node types you see on the canvas or in "
            "dataflow.read that are not listed here cannot take content; use the "
            "'Installed but NOT enlisted in this project' list (when offered) or "
            "delegate authoring instead of creating a node."
        )
    block = (
        "Available node templates (a node.create nodeType or a plan nodeType "
        "MUST be one of these ids; the versioned form "
        "'<packageId>/<templateId>@<major>' is also accepted):\n"
        + "\n".join(_template_line(t) for t in shown)
    )
    # dev/105 S1: the live roster held twelve built-in CODE templates and no
    # note template; the model took the post-it compute node it saw on the
    # canvas — refused, one round spent. A note-composing run is told, in the
    # roster itself, that nothing here renders a note and where the rung is.
    if notes_agent and not any(t.get("presentation") for t in shown):
        block = f"{block}\n{_NO_NOTE_TEMPLATE_LINE}"
    return block


def _enlistable_templates_block(project_id: str, landscape: dict | None, budget: int) -> str | None:
    """The "installed but not enlisted" half of the roster (memo dev/93 D4).

    Separate function, one shared line format: the sections are composed
    together but only this one is grant-gated, and it names the dirName the
    ``package.install`` proposal takes so the model never has to guess it.
    """
    if budget <= 0:
        return None
    rows = [
        r for r in (landscape or {}).get("notEnlisted", []) if r.get("authorable")
    ]
    shown = rows[:budget]
    if len(rows) > len(shown):
        log.warning(
            "Enlistable roster truncated for project %s: %d of %d listed",
            project_id, len(shown), len(rows),
        )
    if not shown:
        return None
    lines = [
        _template_line(r, suffix=f" (package {r['dirName']})") for r in shown
    ]
    return (
        "Installed but NOT enlisted in this project — you already have these; "
        "propose package.install with the named package to use one, and do NOT "
        "author a duplicate package:\n" + "\n".join(lines)
    )


def _available_template(user_key: str, project_id: str, node_type: object) -> tuple[dict | None, str]:
    """Resolve ``node_type`` for node.create against the packages-domain gate
    (dev/48 reuse-first: the agents module owns no template knowledge).

    Thin wrapper over ``resolve_template`` since dev/93 D3 — the versioned
    tolerance added here for dev/90 A14 lived ONLY here, which is why the plan
    path kept refusing ids the model was handed. One gate now serves both;
    node.create is the caller that needs authored content, so it is the one
    that asks for ``require_authorable``.
    Returns ``(entry | None, error_text)``."""
    from utk_curio.backend.app.packages import service as packages_services

    return packages_services.resolve_template(
        user_key, project_id, node_type, require_authorable=True
    )


class _LazyRoster:
    """The Data Lake sources this deployment has, by ``dirName``, read off disk
    on first use, so a pass with no coordinate never touches the roster and
    costs no web budget. An unreadable roster is an empty one."""

    def __init__(self, sources: dict | None = None) -> None:
        self._sources = sources

    def get(self, dir_name: object) -> dict | None:
        if self._sources is None:
            self._sources = {}
            try:
                from utk_curio.backend.app.datalakes.service import DataLakeService

                listing = DataLakeService().list_catalog()
            except Exception:  # noqa: BLE001 - an unreadable roster means "not actionable"
                log.warning("Could not read the Data Lake roster", exc_info=True)
                listing = {}
            for source in listing.get("sources") or []:
                if source.get("dirName"):
                    self._sources[source["dirName"]] = source
        return self._sources.get(dir_name) if isinstance(dir_name, str) else None

    def direct(self) -> str | None:
        """The source that downloads a plain link, when the roster has one."""
        self.get(None)
        for dir_name, source in (self._sources or {}).items():
            if source.get("provider") == "direct" and (source.get("capabilities") or {}).get("download"):
                return dir_name
        return None
