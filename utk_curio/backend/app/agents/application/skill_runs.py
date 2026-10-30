"""The skills a run holds: the list its chat loads from, the skills it is handed, and ``skill.read``.

A skill (``domain/skills.py``, one folder of ``skills/``) tells an agent how
to do a specific task. A run holds its skills as agentskills.io's guide for
clients says (https://agentskills.io/client-implementation/adding-skills-support):

- **The agent's skills** are the ones its manifest names (``skills``), or
  every skill Curio ships when it names none, then what the account changed
  of them in the agent's details (``infrastructure/agent_skills.py``, read at
  the start of each run as the model chosen for it is): the ones it removed
  left out, the ones it added after the rest. Those its preamble holds
  already, as the default preamble holds the core skills, are in the system
  turn, so nothing below lists or hands them again. A name is a skill Curio
  ships or one the account holds of its own (:func:`account_skills`,
  ``repositories/user_skills.py``): one it imported, or its copy of one it
  added from the shared catalog, read leniently and held as written.
- **The packages' skills.** Every run on a dataflow also holds the skills of
  the packages the dataflow uses (``dataflow.packages``), each package's
  ``skills/`` (``packages.dataflow_skill_folders``), whatever its agent
  names, after the agent's own (:func:`package_skills`). They are read
  strictly, as the skills Curio ships are, and held as written: no marker of
  theirs is filled. A name shows once: Curio's skill, then the account's
  skill the agent holds, then the first package's, and a warning names each
  skill left out for it.
- **The catalog.** A chat run lists those skills, each by its name and
  description, under the guide's short instruction (the section
  ``skill-catalog`` of ``frames.md``), and is granted ``skill.read`` to load
  one when a task needs it (:func:`grants`). A run with nothing to list gets
  neither.
- **Handed skills.** A run is handed, in the same ``<skill_content>``
  wrapping and with no model call, the skills that serve what it works on,
  read from each skill's ``metadata``: ``curio-behaviors`` names the node
  behaviors it serves (a template's ``behavior``), ``curio-features`` the
  features of a dataflow it serves (:data:`FEATURES`), ``curio-refusals`` the
  checks whose refusal it answers, by the kind each check records
  (``map_edits.KIND`` and the like), and ``curio-templates``, in a package's
  skill, the templates of that package it serves, by their ids in its
  manifest (:func:`templates_served`), for a package whose templates share
  their behaviors with Curio's own.

  - A chat attached to a node, and a delegated run whose inputs name one, get
    the skills of that node's behavior and of its template.
  - A delegated run that writes code for no node, a package's, gets the
    skills of node code (:data:`CODE_BEHAVIOR`).
  - A delegated run of a mode that reads the dataflow (``dataflowContext``)
    gets the skills of its nodes' behaviors and templates and of its
    features.
  - A Solve round after a check refused the round before gets the skills that
    answer that check (:func:`answering`).
  - Every run of a capability gets the capability's own ``skills``, whatever
    the agent's are.
  - Every run of the agent's instruction gets the instruction's own
    ``skills`` (``prompts.instruction.skills``), the procedures it follows: its
    chat, from its first message, and each capability with no instruction of
    its own, which runs the instruction.
- **Named skills.** A chat message that starts with ``/<name>``, a skill of
  the run's catalog, is handed that skill in its system turn, as the guide has
  a client do when a person activates a skill (``named``, :func:`named_in`).
  A skill the run holds already is not handed again.
- **Loaded skills.** What ``skill.read`` loads in a chat turn is recorded on
  the turn (``skillsLoaded`` in its execution record), and every later run of
  the conversation is handed it again (``kept``), so it outlives the trimming
  of older turns and is never loaded twice. A named skill is kept the same
  way.

A chat run's skills ride its loop context (``skills``), where ``skill.read``
(:func:`read`) answers from them and records what it loads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from utk_curio.backend.app.agents.application import askers as agents_askers
from utk_curio.backend.app.agents.application import dataflow_block as agents_dataflow_block
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import dashboards
from utk_curio.backend.app.agents.domain import plan_topology
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.infrastructure import agent_skills as agent_skill_store
from utk_curio.backend.app.agents.repositories import user_skills
from utk_curio.backend.app.collaboration import owner_uses
from utk_curio.backend.app.packages import service as packages_services

log = logging.getLogger(__name__)

#: The tool a chat run loads a skill or one of its files with.
TOOL = tools.SKILL_TOOL
#: How many ``skill.read`` calls a turn makes before each further one spends
#: one of its tool rounds (``tool_rounds.MAX_TOOL_ROUNDS``).
FREE_READS = 4
#: The keys of a skill's ``metadata`` that name what it serves, each a list of
#: names with a space between each: node behaviors, features of a dataflow,
#: the checks whose refusal it answers, and, in a package's skill, templates
#: of its package.
BEHAVIORS_KEY = "curio-behaviors"
FEATURES_KEY = "curio-features"
REFUSALS_KEY = "curio-refusals"
TEMPLATES_KEY = "curio-templates"
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
    #: What its message named, ``/<name>``, handed in its system turn.
    named: tuple[skill_format.Skill, ...] = ()
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
        its preamble, handed, kept, named, or loaded this turn."""
        return (
            name in self.placed or name in self.loaded
            or any(skill.name == name for skill in (*self.handed, *self.kept, *self.named))
        )

    def pins(self) -> dict:
        """What the run's system turn held of its skills, for its record:
        the catalog's names, the skills it was handed, those it kept from
        earlier turns and those its message named, each only when there is
        one."""
        found = {
            "catalog": self.names,
            "handed": [skill.name for skill in self.handed],
            "kept": [skill.name for skill in self.kept],
            "named": [skill.name for skill in self.named],
        }
        return {key: names for key, names in found.items() if names}


# --- Whose skills -----------------------------------------------------------------


def shipped_skills() -> dict[str, skill_format.Skill]:
    """Every skill Curio ships, read strictly, by name."""
    return {skill.name: skill for skill in skill_format.shipped_skills()}


def account_skills(user_key: str | None) -> dict[str, skill_format.Skill]:
    """The skills the account *user_key* holds of its own
    (``repositories/user_skills.py``): those it imported and its copies of
    skills from the shared catalog, read leniently, as a skill brought from
    elsewhere is, by name. One whose name is not its folder's, or is a skill
    Curio ships, is left out and logged, as is one that cannot be read."""
    if not user_key:
        return {}
    try:
        folders = user_skills.folders(user_key)
    except (OSError, ValueError) as exc:
        log.warning("Could not list the skills of account %s: %s", user_key, exc)
        return {}
    shipped = {folder.name for folder in skill_format.shipped_folders()}
    found: dict[str, skill_format.Skill] = {}
    for folder in folders:
        try:
            skill = skill_format.parse(folder, strict=False)
        except (OSError, ValueError) as exc:  # a SkillError, or a file that is not UTF-8
            log.warning("Runs go without the skill in %s, which cannot be read: %s", folder, exc)
            continue
        if skill.name != folder.name or skill.name in shipped:
            log.warning("Runs go without the skill in %s: its name, %s, is %s", folder, skill.name,
                        "a skill Curio ships" if skill.name in shipped else "not its folder's")
            continue
        found[skill.name] = skill
    return found


def usable_skills(user_key: str | None,
                  shipped: Mapping[str, skill_format.Skill] | None = None) -> dict[str, skill_format.Skill]:
    """Every skill an agent of the account *user_key* may hold, by name: the
    skills Curio ships, then the account's own (:func:`account_skills`)."""
    shipped = shipped_skills() if shipped is None else shipped
    return {**shipped, **account_skills(user_key)}


def agent_skills(manifest, shipped: Mapping[str, skill_format.Skill] | None = None, *,
                 choice: agent_skill_store.SkillChoice | None = None,
                 usable: Mapping[str, skill_format.Skill] | None = None) -> tuple[skill_format.Skill, ...]:
    """The skills the agent *manifest* defines may hold, in its order: the
    ones it names, or every skill Curio ships when it names none (and when
    there is no manifest). With *choice*, what an account changed of them
    (:func:`account_choice`): the ones it removed are left out, and the ones
    it added follow the rest, in the order it added them. A name is found in
    *usable*, the skills an agent of the account may hold
    (:func:`usable_skills`), or only among the skills Curio ships without
    it; a name found nowhere is left out and logged."""
    shipped = shipped_skills() if shipped is None else shipped
    usable = shipped if usable is None else usable
    names = getattr(manifest, "skills", None)
    if names is None:
        found = list(shipped.values())
    else:
        unknown = [name for name in names if name not in usable]
        if unknown:
            log.warning("Agent %s names skills Curio does not ship and its account does not hold, so its runs go "
                        "without them: %s", getattr(manifest, "dir_name", "?"), ", ".join(unknown))
        found = [usable[name] for name in names if name in usable]
    if choice:
        found = [skill for skill in found if skill.name not in choice.removed]
        found += [usable[name] for name in choice.added
                  if name in usable and all(skill.name != name for skill in found)]
    return tuple(found)


def account_choice(user_key: str | None, manifest) -> agent_skill_store.SkillChoice:
    """What the account *user_key* changed of the skills of the agent
    *manifest* defines, by its id (``infrastructure/agent_skills.py``). A file
    that cannot be read changes nothing for a run: it is logged, and the run
    holds the skills the manifest names."""
    agent_id = getattr(manifest, "agent_id", None)
    if not user_key or not isinstance(agent_id, str):
        return agent_skill_store.SkillChoice()
    try:
        return agent_skill_store.default_store().choice(user_key, agent_id)
    except ValueError as exc:  # AgentSkillsError, or a key no store holds
        log.warning("Runs of %s hold the skills its manifest names: %s", agent_id, exc)
        return agent_skill_store.SkillChoice()


def placed_in(preamble: str | None, shipped: Mapping[str, skill_format.Skill]) -> frozenset[str]:
    """The skills *preamble* holds already, by name: each one whose body, as
    an agent reads it, is in the preamble's text."""
    if not preamble:
        return frozenset()
    return frozenset(name for name in shipped if agent_text.skill_text(name) in preamble)


def package_skills(user_key: str | None, spec, shipped: Mapping[str, skill_format.Skill],
                   held: Iterable[skill_format.Skill] = (), *, project_id: str | None = None,
                   asker=None) -> tuple[tuple[str, skill_format.Skill], ...]:
    """The skills of the packages the dataflow *spec* uses, as
    ``(<packageId>@<major>, skill)``: the packages in the lockfile's order,
    each one's skills by name (``packages.dataflow_skill_folders``), each
    read strictly, as the skills Curio ships are. A name shows once, in this
    order: a skill Curio ships (*shipped*), a skill of the account the agent
    holds (*held*), then the first package's. A package's skill of a name
    taken so is left out, and a warning names it, its package and whose
    skill runs hold by that name. One that cannot be read is left out and
    logged.

    A run for an editor the owner invited (*asker*, else the request's
    account, ``askers.editor``) of the dataflow *project_id* holds only the
    skills of the packages its owner added to it herself
    (``collaboration.owner_uses``), as the editor's runs use only her packages
    she added; the owner's runs hold every package's."""
    held_names = {skill.name for skill in held}
    hers = None
    if user_key and project_id and agents_askers.editor(user_key, asker):
        hers = owner_uses.recorded(user_key, project_id)
    found: dict[str, tuple[str, skill_format.Skill]] = {}
    for dir_name, folder in packages_services.dataflow_skill_folders(user_key, spec):
        if hers is not None and not hers.package(dir_name):
            continue
        try:
            skill = skill_format.parse(folder)
        except (OSError, ValueError) as exc:  # a SkillError, or a file that is not UTF-8
            log.warning("Runs on this dataflow go without a skill of %s, which cannot be read: %s", dir_name, exc)
            continue
        if skill.name in shipped:
            log.warning("The skill %s of %s is left out of runs: its name is a skill Curio ships, which they hold",
                        skill.name, dir_name)
        elif skill.name in held_names:
            log.warning("The skill %s of %s is left out of runs: the agent holds the account's own skill of that "
                        "name", skill.name, dir_name)
        elif skill.name in found:
            log.warning("The skill %s of %s is left out of runs: %s ships a skill of that name, which they hold",
                        skill.name, dir_name, found[skill.name][0])
        else:
            found[skill.name] = (dir_name, skill)
    return tuple(found.values())


def _pool(user_key: str | None, manifest, preamble: str | None,
          spec=None, *, project_id: str | None = None,
          asker=None) -> tuple[dict, frozenset[str], tuple[skill_format.Skill, ...], dict[str, str]]:
    """Every skill an agent of the account *user_key* may hold
    (:func:`usable_skills`), the ones *preamble* holds, the skills a run may
    hold that it does not (the agent's, after what the account changed of
    them, then those of the packages the dataflow *spec*, *project_id*, uses,
    :func:`package_skills`, for the run's *asker*), and the package each of
    those comes from, ``<packageId>@<major>``, by the skill's name."""
    shipped = shipped_skills()
    usable = usable_skills(user_key, shipped)
    placed = placed_in(preamble, shipped)
    agents = agent_skills(manifest, shipped, choice=account_choice(user_key, manifest), usable=usable)
    own = tuple(skill for skill in agents if skill.name not in placed)
    packaged = package_skills(user_key, spec, shipped, own, project_id=project_id, asker=asker)
    return usable, placed, (*own, *(skill for _, skill in packaged)), {
        skill.name: dir_name for dir_name, skill in packaged
    }


# --- What serves what ---------------------------------------------------------------


def _named(skill: skill_format.Skill, key: str) -> set[str]:
    return set(str(skill.metadata.get(key) or "").split())


def serving(pool: Iterable[skill_format.Skill], *, behaviors: Iterable[str] = (),
            features: Iterable[str] = (), templates: Iterable[object] = (),
            packages: Mapping[str, str] | None = None) -> tuple[skill_format.Skill, ...]:
    """The skills of *pool*, in its order, whose metadata names one of
    *behaviors* (``curio-behaviors``) or of *features* (``curio-features``),
    or, for a skill a package ships (*packages* names the package of each by
    the skill's name), the template of one of the node types *templates*
    (:func:`templates_served`)."""
    behaviors, features = set(behaviors), set(features)
    node_types = {packages_services.canonical_template_id(t) for t in templates if isinstance(t, str) and t}
    packages = packages or {}
    return tuple(
        skill for skill in pool
        if _named(skill, BEHAVIORS_KEY) & behaviors or _named(skill, FEATURES_KEY) & features
        or templates_served(skill, packages.get(skill.name)) & node_types
    )


def templates_served(skill: skill_format.Skill, package: str | None) -> set[str]:
    """The templates *skill* serves, as canonical node types
    (``<packageId>/<templateId>``), when the package *package*
    (``<packageId>@<major>``) ships it: the templates its ``curio-templates``
    names, by their ids in that package's manifest. None for a skill no
    package ships, so a package's skill serves its own package's nodes and
    no other's."""
    if not package:
        return set()
    package_id = package.rsplit("@", 1)[0]
    return {f"{package_id}/{template}" for template in _named(skill, TEMPLATES_KEY)}


def answering(pool: Iterable[skill_format.Skill], kind: str,
              node_behaviors: Iterable[str] = ()) -> tuple[skill_format.Skill, ...]:
    """The skills of *pool*, in its order, that answer the check whose
    refusal recorded *kind* (their ``curio-refusals`` names it). Of those
    that serve node behaviors, only the ones serving one of *node_behaviors*,
    the behaviors of the node the refused round wrote, when they are known:
    the document check is answered by the Autark skill for an Autark node and
    by the Vega-Lite starter for a chart."""
    node_behaviors = set(node_behaviors)
    found = []
    for skill in pool:
        if kind not in _named(skill, REFUSALS_KEY):
            continue
        serves = _named(skill, BEHAVIORS_KEY)
        if serves and node_behaviors and not serves & node_behaviors:
            continue
        found.append(skill)
    return tuple(found)


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


def _own(names: Iterable[str], usable: Mapping[str, skill_format.Skill], placed: frozenset[str],
         handed: list[skill_format.Skill], whose: str) -> list[skill_format.Skill]:
    """The skills *names* names, a capability's or an instruction's own, that
    *handed* and the preamble (*placed*) do not hold already, from every skill
    an agent of the account may hold (*usable*). A name of no such skill is
    left out and logged."""
    found: list[skill_format.Skill] = []
    for name in names:
        if name not in usable:
            log.warning("%s names a skill Curio does not ship and the account does not hold, %s, so its runs go "
                        "without it", whose, name)
        elif name not in placed and all(skill.name != name for skill in (*handed, *found)):
            found.append(usable[name])
    return found


def _instruction_skills(manifest) -> tuple[str, ...]:
    """The skills every run of the agent's instruction is handed (``prompts.instruction.skills``)."""
    return tuple(getattr(manifest, "instruction_skills", None) or ())


def for_chat(user_key: str, project_id: str, manifest, spec, target, preamble: str | None,
             prior_turns, *, message: str | None = None, asker=None) -> RunSkills:
    """The skills of a chat run of the agent *manifest* defines, on the
    dataflow *spec*, attached to *target*, whose preamble is *preamble*,
    after the turns *prior_turns* of its conversation, for its *message*: the
    catalog of its skills and of the dataflow's packages (for an editor who
    asks, *asker* else the request's account, those the owner added,
    :func:`package_skills`), the ones serving the behavior and the template of
    the node it is attached to, then its instruction's own, those its
    conversation loaded or named before, and those *message* names
    (:func:`named_in`) that it does not hold already."""
    usable, placed, pool, packages = _pool(user_key, manifest, preamble, spec, project_id=project_id, asker=asker)
    node_id = target.get("targetId") if isinstance(target, dict) and target.get("kind") == "node" else None
    node_type = agents_dataflow_block.node_type_of(spec, node_id) if node_id else None
    handed = list(serving(
        pool, behaviors=behaviors_of(user_key, project_id, [node_type]), templates=[node_type], packages=packages,
    ) if node_type else ())
    handed += _own(_instruction_skills(manifest), usable, placed, handed,
                   f"The instruction of agent {getattr(manifest, 'dir_name', '?')}")
    by_name = {skill.name: skill for skill in pool}
    kept = tuple(
        by_name[name] for name in loaded_before(prior_turns)
        if name in by_name and all(skill.name != name for skill in handed)
    )
    held = {skill.name for skill in (*handed, *kept)}
    named = tuple(by_name[name] for name in named_in(message, by_name) if name not in held)
    return RunSkills(catalog=pool, handed=tuple(handed), kept=kept, named=named, placed=placed)


def named_in(message: str | None, listed: Iterable[str]) -> list[str]:
    """The skills *message* names before its first other word, ``/<name>``
    each, as agentskills.io's guide has a person activate a skill: each a
    name of *listed*, the run's catalog, once, in the message's order. The
    first word that names no listed skill ends them, so a path such as
    ``/catalog/agents`` names none."""
    listed = set(listed)
    names: list[str] = []
    for word in (message or "").split():
        name = word[1:] if word.startswith("/") else None
        if not skill_format.is_name(name) or name not in listed:
            break
        if name not in names:
            names.append(name)
    return names


def for_delegated(user_key: str, project_id: str, manifest, capability: str, inputs, spec,
                  preamble: str | None, *, refused: str | None = None, asker=None) -> RunSkills:
    """The skills a delegated run of *capability* of the agent *manifest*
    defines is handed, with *inputs*, in the dataflow *spec*: those serving
    what it works on, of its agent and of the dataflow's packages (for an
    editor who asks, *asker* else the request's account, those the owner
    added, :func:`package_skills`), those answering the check that refused
    its last round (*refused*, the kind that refusal records), then the
    capability's own, then, for a capability with no instruction of its own,
    which runs the agent's instruction, the instruction's. It lists none: it
    holds no tool."""
    usable, placed, pool, packages = _pool(user_key, manifest, preamble, spec, project_id=project_id, asker=asker)
    behaviors: set[str] = set()
    features: set[str] = set()
    templates: list[object] = []
    node_type = agents_dataflow_block.named_node_type(inputs, lambda: spec)
    node_behaviors = behaviors_of(user_key, project_id, [node_type]) if node_type else set()
    if node_type:
        behaviors |= node_behaviors
        templates.append(node_type)
    elif capability in agents_dataflow_block.CODE_CAPABILITIES:
        behaviors.add(CODE_BEHAVIOR)
    elif DATAFLOW_CONTEXT in _reads(manifest, capability):
        templates = [n.get("type") for n in _dicts(_dataflow(spec).get("nodes"))]
        behaviors |= behaviors_of(user_key, project_id, templates)
        features |= dataflow_features(spec)
    handed = list(serving(pool, behaviors=behaviors, features=features, templates=templates, packages=packages))
    if isinstance(refused, str) and refused:
        handed += [skill for skill in answering(pool, refused, node_behaviors) if skill not in handed]
    declared = manifest.capability(capability) if manifest is not None else None
    handed += _own(declared.skills if declared is not None else (), usable, placed, handed,
                   f"Capability {capability}")
    if declared is None or not declared.instruction:
        handed += _own(_instruction_skills(manifest), usable, placed, handed,
                       f"The instruction of agent {getattr(manifest, 'dir_name', '?')}")
    return RunSkills(handed=tuple(handed), placed=placed)


def loaded_before(turns) -> list[str]:
    """The skills *turns*, a conversation's, took in for the rest of it,
    oldest first and each once: of each turn, those its message named
    (``pins.skills.named`` in its execution record), then those ``skill.read``
    loaded (``skillsLoaded``)."""
    names: list[str] = []
    for turn in turns or ():
        execution = turn.get("execution") if isinstance(turn, dict) else None
        if not isinstance(execution, dict):
            continue
        pins = execution.get("pins")
        held = pins.get("skills") if isinstance(pins, dict) else None
        named = held.get("named") if isinstance(held, dict) else None
        loaded = execution.get("skillsLoaded")
        for name in (*(named if isinstance(named, list) else ()), *(loaded if isinstance(loaded, list) else ())):
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


def text_of(skill: skill_format.Skill) -> str:
    """*skill*'s body as an agent reads it, without its final line breaks: a
    skill Curio ships rendered, its markers filled (``agent_text.skill_text``),
    and any other, a package's, as written."""
    if skill_format.is_shipped(skill):
        return agent_text.skill_text(skill.name)
    return skill.body.rstrip("\n")


def content(skill: skill_format.Skill, *, readable: bool) -> str:
    """*skill* as a run holds it: its body as an agent reads it
    (:func:`text_of`), its frontmatter left out, wrapped as
    ``<skill_content name="...">``. A run that can read the skill's files
    (*readable*) also gets their list, ``<skill_resources>``, without their
    text."""
    parts = [f"<skill_content name={quoteattr(skill.name)}>", text_of(skill)]
    if readable and skill.files:
        files = "\n".join(f"  <file>{escape(path)}</file>" for path in skill.files)
        parts += ["", agent_text.section(builtin.FRAMES_FILE, FILES_SECTION),
                  f"<skill_resources>\n{files}\n</skill_resources>"]
    parts.append("</skill_content>")
    return "\n".join(parts)


def skills_text(run: RunSkills) -> str | None:
    """The skills a run's system turn holds, each wrapped
    (:func:`content`): those it is handed, then those it kept, then those its
    message named. None when it holds none."""
    held = (*run.handed, *run.kept, *run.named)
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
