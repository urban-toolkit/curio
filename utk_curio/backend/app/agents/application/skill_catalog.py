"""Skills as the Agent Catalog shows them, and what an account changes of an agent's skills.

The Agent Catalog lists skills beside agents (``routes/skills.py``):

- :func:`skills_listing`: every skill Curio ships, as a card: its name, its
  description and facts (``license``, ``compatibility``, the author and
  version its ``metadata`` gives), its other files, what it serves (the kinds
  of node whose templates name one of its ``curio-behaviors``, and its
  ``curio-features``), whether every call holds it (``core``: the preamble
  Curio's agents read places it), and the agents that use it, after the
  account's changes.
- :func:`skill_text`: one skill's body as an agent reads it, and its files.
- :func:`agent_skill_rows`: one agent's skills as its details list them: the
  core skills its preamble holds, those its manifest names after the
  account's changes, and those its instruction or a capability of it names
  as its own; which the account may remove, and which it may add.
- :func:`add_skill`, :func:`remove_skill` and :func:`restore_skills`: the
  account's changes (``infrastructure/agent_skills.py``), each checked. A run
  reads them when it starts (``skill_runs.account_choice``), so its catalog
  and the skills it is handed follow them.
- :func:`run_skills`: the skills a chat of one attachment lists, which ``/``
  in its composer offers.
"""

from __future__ import annotations

from dataclasses import dataclass

from utk_curio.backend.app.agents.application import catalog
from utk_curio.backend.app.agents.application import skill_runs
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application.turns import prompts
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.infrastructure import agent_skills as agent_skill_store
from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.packages import service as packages_services

#: The keys of a skill's ``metadata`` that name its author and version.
AUTHOR_KEY = "author"
VERSION_KEY = "version"


# --- The agents ----------------------------------------------------------------------


def _agents(user_key: str) -> list[AgentManifest]:
    """Every agent the account sees, each once by coordinate, in this order:
    the agents Curio ships (its helpers too), the published ones, then the
    account's own."""
    found: dict[str, AgentManifest] = {}
    for m in builtin.list_builtin_manifests():
        found[m.dir_name] = m
    for m in publications.list_published():
        found.setdefault(m.dir_name, m)
    for coord in sorted(imports.load_imported_agents(user_key)):
        m = None if builtin.is_internal(coord) else catalog._resolve_definition(user_key, coord)
        if m is not None:
            found[coord] = m
    return list(found.values())


@dataclass(frozen=True)
class _Held:
    """What an agent holds for an account, by skill name."""

    #: The skills its preamble places, which every call holds.
    placed: frozenset[str]
    #: Its own skills after the account's changes, those placed left out.
    own: list
    #: The skills its instruction names as its own, which its chat holds
    #: from its first message whatever its skills are.
    chat: list[str]
    #: Each skill a mode of it names as its own, with those modes' labels.
    modes: dict[str, list[str]]
    #: The skills only a capability that is no mode names as its own: a
    #: call another agent asks it for, which a built-in leaves unlabeled.
    asked: list[str]

    def always(self, name: str) -> bool:
        """Whether a run of the agent holds *name* whatever its skills are."""
        return name in self.placed or name in self.chat or name in self.modes or name in self.asked


def _own_modes(m: AgentManifest) -> tuple[dict[str, list[str]], list[str]]:
    """Each skill a capability of *m* names as its own, which the
    capability's runs hold whatever the agent's skills are: with the labels
    of the modes that name it, and apart, those a capability that is no mode
    names (``catalog.agent_modes`` leaves out a built-in's unlabeled
    capability, a call another agent asks it for)."""
    labels = {cap: mode["label"] for mode in catalog.agent_modes(m) for cap in mode["capabilities"]}
    found: dict[str, list[str]] = {}
    asked: list[str] = []
    for capability in m.capabilities:
        label = labels.get(capability.id)
        for name in capability.skills:
            if label is None:
                if name not in asked:
                    asked.append(name)
            elif label not in found.setdefault(name, []):
                found[name].append(label)
    return found, asked


def _held(user_key: str, m: AgentManifest, shipped: dict) -> _Held:
    """What the agent *m* holds for the account *user_key* (:class:`_Held`)."""
    placed = skill_runs.placed_in(prompts._resolve_prompt_text(user_key, m.dir_name, "system"), shipped)
    choice = skill_runs.account_choice(user_key, m)
    own = [skill for skill in skill_runs.agent_skills(m, shipped, choice=choice) if skill.name not in placed]
    chat = [name for name in dict.fromkeys(m.instruction_skills) if name in shipped and name not in placed]
    modes, asked = _own_modes(m)
    return _Held(placed=placed, own=own, chat=chat, modes=modes, asked=asked)


def _require_agent(user_key: str, coord: str) -> AgentManifest:
    m = None if builtin.is_internal(coord) else catalog._resolve_definition(user_key, coord)
    if m is None:
        raise AgentServiceError(f"no agent definition {coord}", 404)
    return m


def _require_changeable(user_key: str, m: AgentManifest) -> None:
    """Refuse an agent whose skills the account may not change: one that is
    neither a catalog card, a published agent nor the account's own, as for
    the model chosen for it."""
    if m.agent_id not in {row["id"] for row in catalog.choosable_agents(user_key)}:
        raise AgentServiceError(f"{m.name} is not an agent whose skills you can change", 400)


# --- The skills ----------------------------------------------------------------------


def _node_kinds(skill: skill_format.Skill, behaviors_by_template: dict[str, str],
                labels: dict[str, str]) -> list[str]:
    """The labels of the templates whose behavior *skill* serves, the base
    package's first, each once."""
    served = set(str(skill.metadata.get(skill_runs.BEHAVIORS_KEY) or "").split())
    found: list[str] = []
    for template_id, label in labels.items():
        if behaviors_by_template.get(template_id) in served and label not in found:
            found.append(label)
    return found


def skills_listing(user_key: str) -> list[dict]:
    """Every skill Curio ships, as the Agent Catalog shows it (the module's
    docstring says what each card holds), in its folder's order."""
    shipped = skill_runs.shipped_skills()
    core = skill_runs.placed_in(builtin.read_page(builtin.PREAMBLE_FILE, wanted_by="the skills listing"), shipped)
    behaviors_by_template = packages_services.catalog_template_behaviors()
    labels = packages_services.catalog_template_labels()
    users: dict[str, list[dict]] = {name: [] for name in shipped}
    for m in _agents(user_key):
        held = _held(user_key, m, shipped)
        added = set(skill_runs.account_choice(user_key, m).added)
        names = [*sorted(held.placed), *(skill.name for skill in held.own), *held.chat, *held.modes, *held.asked]
        for name in dict.fromkeys(names):
            if name in users:
                users[name].append({
                    "id": m.agent_id, "name": m.name, "coord": m.dir_name,
                    "card": not builtin.is_internal(m.dir_name),
                    "added": name in added and name not in held.placed,
                    "always": held.always(name),
                })
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "license": skill.license,
            "compatibility": skill.compatibility,
            "author": skill.metadata.get(AUTHOR_KEY),
            "version": skill.metadata.get(VERSION_KEY),
            "files": list(skill.files),
            "behaviors": str(skill.metadata.get(skill_runs.BEHAVIORS_KEY) or "").split(),
            "features": str(skill.metadata.get(skill_runs.FEATURES_KEY) or "").split(),
            "nodeKinds": _node_kinds(skill, behaviors_by_template, labels),
            "core": name in core,
            "agents": users[name],
        }
        for name, skill in shipped.items()
    ]


def skill_text(name: str) -> dict:
    """The skill Curio ships as *name*: its body as an agent reads it, its
    frontmatter left out and its markers filled, and its other files."""
    shipped = skill_runs.shipped_skills()
    if name not in shipped:
        raise AgentServiceError(f"Curio ships no skill named {name}", 404)
    return {"name": name, "text": agent_text.skill_text(name), "files": list(shipped[name].files)}


# --- One agent's skills ----------------------------------------------------------------


def agent_skill_rows(user_key: str, coord: str, *, editable: bool = True) -> dict:
    """The skills of the agent at *coord*, as its details list them: each
    ``{name, description, core, added, chat, modes, asked, removable}``
    (:class:`_Held` says what ``chat``, ``modes`` and ``asked`` are), the
    core skills its preamble holds first, then its own in its order, then
    those only its instruction names, then those only its capabilities name;
    ``addable``, the skills it does not hold; and ``changed``, whether the
    account changed them, which Restore undoes. Only a skill its runs hold
    whatever its skills are is not ``removable``."""
    m = _require_agent(user_key, coord)
    shipped = skill_runs.shipped_skills()
    held = _held(user_key, m, shipped)
    choice = skill_runs.account_choice(user_key, m)
    changeable = editable and m.agent_id in {row["id"] for row in catalog.choosable_agents(user_key)}

    def row(skill: skill_format.Skill, *, core: bool = False) -> dict:
        return {
            "name": skill.name,
            "description": skill.description,
            "core": core,
            "added": skill.name in choice.added and not core,
            "chat": skill.name in held.chat,
            "modes": held.modes.get(skill.name, []),
            "asked": skill.name in held.asked,
            "removable": changeable and not held.always(skill.name),
        }

    rows = [row(shipped[name], core=True) for name in shipped if name in held.placed]
    rows += [row(skill) for skill in held.own]
    listed = {entry["name"] for entry in rows}
    for name in dict.fromkeys([*held.chat, *held.modes, *held.asked]):
        if name in shipped and name not in listed:
            rows.append(row(shipped[name]))
            listed.add(name)
    return {
        "coord": m.dir_name,
        "agentId": m.agent_id,
        "skills": rows,
        "addable": [
            {"name": name, "description": skill.description}
            for name, skill in shipped.items() if changeable and name not in listed
        ],
        "changed": bool(choice),
        "editable": changeable,
    }


def _shipped_name(name: object, shipped: dict) -> str:
    if not isinstance(name, str) or name not in shipped:
        raise AgentServiceError(f"Curio ships no skill named {name}", 404)
    return name


def add_skill(user_key: str, coord: str, name: object) -> dict:
    """Add the skill *name* to the agent at *coord*, for the account: a
    skill its manifest left out, or one the account removed. One its
    preamble holds is refused; one it holds already changes nothing."""
    m = _require_agent(user_key, coord)
    _require_changeable(user_key, m)
    shipped = skill_runs.shipped_skills()
    name = _shipped_name(name, shipped)
    if name in _held(user_key, m, shipped).placed:
        raise AgentServiceError(f"{m.name} holds {name} in every call already", 400)
    named = {skill.name for skill in skill_runs.agent_skills(m, shipped)}

    def change(current: agent_skill_store.SkillChoice) -> agent_skill_store.SkillChoice:
        removed = tuple(skill for skill in current.removed if skill != name)
        added = current.added if name in named or name in current.added else (*current.added, name)
        return agent_skill_store.SkillChoice(added=added, removed=removed)

    _store_update(user_key, m, change)
    return agent_skill_rows(user_key, coord)


def remove_skill(user_key: str, coord: str, name: object) -> dict:
    """Remove the skill *name* from the agent at *coord*, for the account.
    A core skill and a skill its instruction or a capability of it names as
    its own are refused, as is a skill it does not hold."""
    m = _require_agent(user_key, coord)
    _require_changeable(user_key, m)
    shipped = skill_runs.shipped_skills()
    name = _shipped_name(name, shipped)
    held = _held(user_key, m, shipped)
    if name in held.placed:
        raise AgentServiceError(f"{name} is in every call of {m.name}, so it cannot be removed", 400)
    if name in held.chat:
        raise AgentServiceError(f"{name} is always held by the chat of {m.name}, so it cannot be removed", 400)
    if name in held.modes:
        raise AgentServiceError(
            f"{name} is always held by {', '.join(held.modes[name])} of {m.name}, so it cannot be removed", 400,
        )
    if name in held.asked:
        raise AgentServiceError(
            f"{name} is always held when another agent asks {m.name} for its work, so it cannot be removed", 400,
        )
    if all(skill.name != name for skill in held.own):
        raise AgentServiceError(f"{m.name} has no skill {name}", 404)
    named = {skill.name for skill in skill_runs.agent_skills(m, shipped)}

    def change(current: agent_skill_store.SkillChoice) -> agent_skill_store.SkillChoice:
        added = tuple(skill for skill in current.added if skill != name)
        removed = current.removed if name not in named or name in current.removed else (*current.removed, name)
        return agent_skill_store.SkillChoice(added=added, removed=removed)

    _store_update(user_key, m, change)
    return agent_skill_rows(user_key, coord)


def restore_skills(user_key: str, coord: str) -> dict:
    """Give the agent at *coord* back the skills its manifest names, Curio's
    list for an agent Curio ships: the account's changes are dropped."""
    m = _require_agent(user_key, coord)
    _require_changeable(user_key, m)
    _store_update(user_key, m, lambda _current: agent_skill_store.SkillChoice())
    return agent_skill_rows(user_key, coord)


def _store_update(user_key: str, m: AgentManifest, change) -> None:
    try:
        agent_skill_store.default_store().update(user_key, m.agent_id, change)
    except agent_skill_store.AgentSkillsError as exc:
        raise AgentServiceError(str(exc), exc.status) from exc


# --- A chat's skills ------------------------------------------------------------------


def run_skills(user_key: str, project_id: str, attachment_id: str) -> list[dict]:
    """The skills the next run of the chat *attachment_id* lists, in its
    catalog's order, each ``{name, description, held}``: ``held`` when the
    chat holds it already, handed for its node or kept from an earlier turn,
    so naming it hands nothing."""
    spec = spec_reads._read_spec_or_404(user_key, project_id)
    record = spec_reads._record_or_404(spec, attachment_id)
    coord = record.get("coord", "")
    m = catalog._resolve_definition(user_key, coord)
    preamble = prompts._resolve_prompt_text(user_key, coord, "system")
    session_id = record.get("sessionId")
    prior = sessions.read_turns(user_key, project_id, session_id) if isinstance(session_id, str) else []
    run = skill_runs.for_chat(user_key, project_id, m, spec, record.get("target"), preamble, prior)
    held = {skill.name for skill in (*run.handed, *run.kept)}
    return [{"name": skill.name, "description": skill.description, "held": skill.name in held}
            for skill in run.catalog]
