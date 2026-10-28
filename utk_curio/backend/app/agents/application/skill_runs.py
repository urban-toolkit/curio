"""The skills a run holds: the list its chat loads from, the skills it is handed, and ``skill.read``.

A skill (``domain/skills.py``, one folder of ``skills/``) tells an agent how
to do a specific task. A run holds its skills as agentskills.io's guide for
clients says (https://agentskills.io/client-implementation/adding-skills-support):

- **The agent's skills** are the ones its manifest names (``skills``), or
  every skill Curio ships when it names none. Those its preamble holds
  already, as the default preamble holds the core skills, are in the system
  turn, so nothing below lists or hands them again.
- **The catalog.** A chat run lists the agent's other skills, each by its
  name and description, under the guide's short instruction (the section
  ``skill-catalog`` of ``frames.md``), and is granted ``skill.read`` to load
  one when a task needs it (:func:`grants`). A run with nothing to list gets
  neither.
- **Handed skills.** A run is handed, in the same ``<skill_content>``
  wrapping and with no model call, the agent's skills that serve what it
  works on, read from each skill's ``metadata``: ``curio-behaviors`` names
  the node behaviors it serves (a template's ``behavior``) and
  ``curio-features`` the features of a dataflow it serves (:data:`FEATURES`).

  - A chat attached to a node, and a delegated run whose inputs name one, get
    the skills of that node's behavior.
  - A delegated run that writes code for no node, a package's, gets the
    skills of node code (:data:`CODE_BEHAVIOR`).
  - A delegated run of a mode that reads the dataflow (``dataflowContext``)
    gets the skills of its nodes' behaviors and of its features.
  - A Solve round after a check refused the round before gets the skills of
    what that check guards (:data:`GUARDS`).
  - Every run of a capability gets the capability's own ``skills``, whatever
    the agent's are.
- **Loaded skills.** What ``skill.read`` loads in a chat turn is recorded on
  the turn (``skillsLoaded`` in its execution record), and every later run of
  the conversation is handed it again (``kept``), so it outlives the trimming
  of older turns and is never loaded twice.

A chat run's skills ride its loop context (``skills``), where ``skill.read``
(:func:`read`) answers from them and records what it loads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from utk_curio.backend.app.agents.application import dataflow_block as agents_dataflow_block
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import dashboards
from utk_curio.backend.app.agents.domain import map_edits
from utk_curio.backend.app.agents.domain import plan_topology
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.packages import service as packages_services

log = logging.getLogger(__name__)

#: The tool a chat run loads a skill or one of its files with.
TOOL = tools.SKILL_TOOL
#: How many ``skill.read`` calls a turn makes before each further one spends
#: one of its tool rounds (``tool_rounds.MAX_TOOL_ROUNDS``).
FREE_READS = 4
#: The keys of a skill's ``metadata`` that name what it serves, each a list of
#: names with a space between each.
BEHAVIORS_KEY = "curio-behaviors"
FEATURES_KEY = "curio-features"
#: The features of a dataflow a skill can serve, by the names its
#: ``curio-features`` gives them: scenario boxes, interaction edges and nodes
#: pinned to the dashboard.
SCENARIO_BOXES = "scenario-boxes"
INTERACTION_EDGES = "interaction-edges"
PINNED_TILES = "pinned-tiles"
FEATURES = (SCENARIO_BOXES, INTERACTION_EDGES, PINNED_TILES)
#: The behavior of node code: what a run that writes code for no node writes.
CODE_BEHAVIOR = "code"
#: What a mode reads when it reads the whole dataflow (a capability's ``reads``).
DATAFLOW_CONTEXT = "dataflowContext"
#: The kind a Solve round fails with when the document it wrote is invalid.
DOCUMENT_KIND = "document-invalid"
#: In :data:`GUARDS`, the behavior of the node the refused round wrote.
NODE_BEHAVIOR = "node"
#: What each check of a Solve round guards, by the kind its refusal records:
#: ``("behavior", <behavior>)`` or ``("feature", <feature>)``. The next round
#: is handed the skills serving it.
GUARDS: Mapping[str, tuple[str, str]] = {
    map_edits.KIND: ("behavior", map_edits.BEHAVIOR),
    dashboards.KIND: ("feature", PINNED_TILES),
    DOCUMENT_KIND: ("behavior", NODE_BEHAVIOR),
    source_grounding.CODE_KIND: ("behavior", CODE_BEHAVIOR),
    source_grounding.SOURCE_KIND: ("behavior", CODE_BEHAVIOR),
}
#: The sections of ``frames.md`` that hold the catalog's instruction and the
#: line before a skill's list of files.
CATALOG_SECTION = "skill-catalog"
FILES_SECTION = "skill-files"


@dataclass
class RunSkills:
    """The skills one run holds, each list in the order it is listed in."""

    #: What its chat may load with ``skill.read``, listed in its system turn.
    catalog: tuple[skill_format.Skill, ...] = ()
    #: What it is handed in its system turn.
    handed: tuple[skill_format.Skill, ...] = ()
    #: What earlier turns of its conversation loaded, handed again.
    kept: tuple[skill_format.Skill, ...] = ()
    #: The skills its preamble holds already, by name.
    placed: frozenset[str] = frozenset()
    #: What ``skill.read`` loaded this turn, by name, in order.
    loaded: list[str] = field(default_factory=list)
    #: The files ``skill.read`` read this turn, as ``(skill, path)``.
    files_read: list[tuple[str, str]] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        """The names ``skill.read`` takes: the catalog's."""
        return [skill.name for skill in self.catalog]

    def holds(self, name: str) -> bool:
        """Whether the run's conversation holds the skill *name* already: in
        its preamble, handed, kept, or loaded this turn."""
        return (
            name in self.placed or name in self.loaded
            or any(skill.name == name for skill in (*self.handed, *self.kept))
        )

    def pins(self) -> dict:
        """What the run's system turn held of its skills, for its record:
        the catalog's names, the skills it was handed and those it kept from
        earlier turns, each only when there is one."""
        found = {
            "catalog": self.names,
            "handed": [skill.name for skill in self.handed],
            "kept": [skill.name for skill in self.kept],
        }
        return {key: names for key, names in found.items() if names}


# --- Whose skills -----------------------------------------------------------------


def shipped_skills() -> dict[str, skill_format.Skill]:
    """Every skill Curio ships, read strictly, by name."""
    return {skill.name: skill for skill in skill_format.shipped_skills()}


def agent_skills(manifest, shipped: Mapping[str, skill_format.Skill] | None = None) -> tuple[skill_format.Skill, ...]:
    """The skills the agent *manifest* defines may hold, in its order: the
    ones it names, or every skill Curio ships when it names none (and when
    there is no manifest). A name Curio ships no skill by is left out and
    logged."""
    shipped = shipped_skills() if shipped is None else shipped
    names = getattr(manifest, "skills", None)
    if names is None:
        return tuple(shipped.values())
    unknown = [name for name in names if name not in shipped]
    if unknown:
        log.warning("Agent %s names skills Curio does not ship, so its runs go without them: %s",
                    getattr(manifest, "dir_name", "?"), ", ".join(unknown))
    return tuple(shipped[name] for name in names if name in shipped)


def placed_in(preamble: str | None, shipped: Mapping[str, skill_format.Skill]) -> frozenset[str]:
    """The skills *preamble* holds already, by name: each one whose body, as
    an agent reads it, is in the preamble's text."""
    if not preamble:
        return frozenset()
    return frozenset(name for name in shipped if agent_text.skill_text(name) in preamble)


def _pool(manifest, preamble: str | None) -> tuple[dict, frozenset[str], tuple[skill_format.Skill, ...]]:
    """Every skill Curio ships, the ones *preamble* holds, and the agent's
    skills it does not."""
    shipped = shipped_skills()
    placed = placed_in(preamble, shipped)
    return shipped, placed, tuple(skill for skill in agent_skills(manifest, shipped) if skill.name not in placed)


# --- What serves what ---------------------------------------------------------------


def _named(skill: skill_format.Skill, key: str) -> set[str]:
    return set(str(skill.metadata.get(key) or "").split())


def serving(pool: Iterable[skill_format.Skill], *, behaviors: Iterable[str] = (),
            features: Iterable[str] = ()) -> tuple[skill_format.Skill, ...]:
    """The skills of *pool*, in its order, whose metadata names one of
    *behaviors* (``curio-behaviors``) or of *features* (``curio-features``)."""
    behaviors, features = set(behaviors), set(features)
    return tuple(
        skill for skill in pool
        if _named(skill, BEHAVIORS_KEY) & behaviors or _named(skill, FEATURES_KEY) & features
    )


def _dataflow(spec) -> dict:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    return dataflow if isinstance(dataflow, dict) else {}


def _dicts(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def behaviors_of(user_key: str, project_id: str, node_types: Iterable[object]) -> set[str]:
    """The behaviors the templates of *node_types* name, as a run finds each
    template (``packages.template_behavior``)."""
    found: set[str] = set()
    for node_type in sorted({t for t in node_types if isinstance(t, str) and t}):
        behavior = packages_services.template_behavior(user_key, project_id, node_type)
        if behavior:
            found.add(behavior)
    return found


def dataflow_features(spec) -> set[str]:
    """The features of :data:`FEATURES` the dataflow *spec* holds: a scenario,
    an interaction edge (``plan_topology.is_interaction_edge``), a node pinned
    to its dashboard (``dashboards.is_pinned``)."""
    dataflow = _dataflow(spec)
    found: set[str] = set()
    if _dicts(dataflow.get("scenarios")):
        found.add(SCENARIO_BOXES)
    if any(plan_topology.is_interaction_edge(edge) for edge in _dicts(dataflow.get("edges"))):
        found.add(INTERACTION_EDGES)
    if any(dashboards.is_pinned(node) for node in _dicts(dataflow.get("nodes"))):
        found.add(PINNED_TILES)
    return found


def _reads(manifest, capability: str) -> tuple[str, ...]:
    """What a run of *capability* reads: the capability's own ``reads``, else
    the agent's (``inputs.reads``)."""
    if manifest is None:
        return ()
    declared = manifest.capability(capability)
    if declared is not None and declared.reads:
        return tuple(declared.reads)
    return tuple(manifest.inputs_reads)


# --- A run's skills ------------------------------------------------------------------


def for_chat(user_key: str, project_id: str, manifest, spec, target, preamble: str | None,
             prior_turns) -> RunSkills:
    """The skills of a chat run of the agent *manifest* defines, attached to
    *target*, whose preamble is *preamble*, after the turns *prior_turns* of
    its conversation: the catalog of its skills, the ones serving the
    behavior of the node it is attached to, and those its conversation loaded
    before."""
    _shipped, placed, pool = _pool(manifest, preamble)
    node_id = target.get("targetId") if isinstance(target, dict) and target.get("kind") == "node" else None
    node_type = agents_dataflow_block.node_type_of(spec, node_id) if node_id else None
    handed = serving(pool, behaviors=behaviors_of(user_key, project_id, [node_type])) if node_type else ()
    by_name = {skill.name: skill for skill in pool}
    kept = tuple(
        by_name[name] for name in loaded_before(prior_turns)
        if name in by_name and all(skill.name != name for skill in handed)
    )
    return RunSkills(catalog=pool, handed=handed, kept=kept, placed=placed)


def for_delegated(user_key: str, project_id: str, manifest, capability: str, inputs, spec,
                  preamble: str | None, *, refused: str | None = None) -> RunSkills:
    """The skills a delegated run of *capability* of the agent *manifest*
    defines is handed, with *inputs*, in the dataflow *spec*: those serving
    what it works on, those serving what the check that refused its last
    round guards (*refused*, the kind that refusal records), then the
    capability's own. It lists none: it holds no tool."""
    shipped, placed, pool = _pool(manifest, preamble)
    behaviors: set[str] = set()
    features: set[str] = set()
    node_type = agents_dataflow_block.named_node_type(inputs, lambda: spec)
    if node_type:
        behaviors |= behaviors_of(user_key, project_id, [node_type])
    elif capability in agents_dataflow_block.CODE_CAPABILITIES:
        behaviors.add(CODE_BEHAVIOR)
    elif DATAFLOW_CONTEXT in _reads(manifest, capability):
        behaviors |= behaviors_of(user_key, project_id, [n.get("type") for n in _dicts(_dataflow(spec).get("nodes"))])
        features |= dataflow_features(spec)
    guard = GUARDS.get(refused) if isinstance(refused, str) else None
    if guard is not None:
        key, value = guard
        if key == "feature":
            features.add(value)
        elif value == NODE_BEHAVIOR:
            behaviors |= behaviors_of(user_key, project_id, [node_type])
        else:
            behaviors.add(value)
    handed = list(serving(pool, behaviors=behaviors, features=features))
    declared = manifest.capability(capability) if manifest is not None else None
    for name in declared.skills if declared is not None else ():
        if name not in shipped:
            log.warning("Capability %s names a skill Curio does not ship, %s, so its runs go without it",
                        capability, name)
        elif name not in placed and all(skill.name != name for skill in handed):
            handed.append(shipped[name])
    return RunSkills(handed=tuple(handed), placed=placed)


def loaded_before(turns) -> list[str]:
    """The skills ``skill.read`` loaded in *turns*, a conversation's, oldest
    first and each once: what each turn's execution record lists as
    ``skillsLoaded``."""
    names: list[str] = []
    for turn in turns or ():
        execution = turn.get("execution") if isinstance(turn, dict) else None
        loaded = execution.get("skillsLoaded") if isinstance(execution, dict) else None
        for name in loaded if isinstance(loaded, list) else ():
            if isinstance(name, str) and name not in names:
                names.append(name)
    return names


def grants(granted: Iterable[str], run: RunSkills) -> list[str]:
    """*granted* with ``skill.read`` exactly when *run* lists skills: a run
    loads from its catalog, and a run with none holds no such tool, whatever
    its manifest asks for."""
    others = [tool_id for tool_id in granted if tool_id != TOOL]
    return [*others, TOOL] if run.catalog else others


# --- What a run reads of them ---------------------------------------------------------


def catalog_text(run: RunSkills) -> str | None:
    """The catalog a chat run's system turn lists: the guide's instruction,
    then ``<available_skills>`` with each skill's name and description.
    None for a run that lists none."""
    if not run.catalog:
        return None
    entries = "\n".join(
        f"  <skill>\n    <name>{escape(skill.name)}</name>\n"
        f"    <description>{escape(skill.description)}</description>\n  </skill>"
        for skill in run.catalog
    )
    instruction = agent_text.section(builtin.FRAMES_FILE, CATALOG_SECTION)
    return f"{instruction}\n\n<available_skills>\n{entries}\n</available_skills>"


def content(skill: skill_format.Skill, *, readable: bool) -> str:
    """*skill* as a run holds it: its body as an agent reads it, its
    frontmatter left out, wrapped as ``<skill_content name="...">``. A run
    that can read the skill's files (*readable*) also gets their list,
    ``<skill_resources>``, without their text."""
    parts = [f"<skill_content name={quoteattr(skill.name)}>", agent_text.skill_text(skill.name)]
    if readable and skill.files:
        files = "\n".join(f"  <file>{escape(path)}</file>" for path in skill.files)
        parts += ["", agent_text.section(builtin.FRAMES_FILE, FILES_SECTION),
                  f"<skill_resources>\n{files}\n</skill_resources>"]
    parts.append("</skill_content>")
    return "\n".join(parts)


def skills_text(run: RunSkills) -> str | None:
    """The skills a run's system turn holds, each wrapped
    (:func:`content`): those it is handed, then those it kept. None when it
    holds none."""
    held = (*run.handed, *run.kept)
    if not held:
        return None
    return "\n\n".join(content(skill, readable=bool(run.catalog)) for skill in held)


def read(run: RunSkills, params) -> tuple[str, str]:
    """``skill.read``: ``(status, text)``. The skill ``name`` names, one of
    the run's catalog, wrapped as :func:`content` gives it, or one of its
    files when ``path`` names one. A skill or file the conversation holds
    already is answered with a line that says so instead of its text, and
    what is loaded is recorded on *run*. A name the catalog does not list,
    or a path the skill holds no file at, is refused (``refused``)."""
    params = params if isinstance(params, dict) else {}
    listed = {skill.name: skill for skill in run.catalog}
    name = params.get("name")
    if not isinstance(name, str) or name not in listed:
        return "refused", agent_text.message("skills.not-listed", name=repr(name), names=", ".join(listed))
    skill = listed[name]
    path = params.get("path")
    if path is None or path == "":
        if run.holds(name):
            return "ok", agent_text.message("skills.already-loaded", name=name)
        run.loaded.append(name)
        return "ok", content(skill, readable=True)
    if not isinstance(path, str) or path not in skill.files:
        return "refused", agent_text.message(
            "skills.no-such-file", name=name, path=repr(path), files=", ".join(skill.files) or "none",
        )
    if (name, path) in run.files_read:
        return "ok", agent_text.message("skills.file-already-read", name=name, path=path)
    run.files_read.append((name, path))
    text = (skill.folder / path).read_text(encoding="utf-8", errors="replace").rstrip("\n")
    if len(text) > tools.TOOL_RESULT_MAX_CHARS:
        text = text[:tools.TOOL_RESULT_MAX_CHARS] + "\n" + agent_text.message("tools.result-truncated")
    return "ok", f"<skill_file name={quoteattr(name)} path={quoteattr(path)}>\n{text}\n</skill_file>"
