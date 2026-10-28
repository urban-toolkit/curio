"""Skills as the Agent Catalog shows them, and what an account changes of an agent's skills.

The Agent Catalog lists skills beside agents (``routes/skills.py``). An
account sees three kinds (:func:`seen_skills`): the skills Curio ships, those
it holds of its own (``repositories/user_skills.py``: the ones it imported,
and its copies of skills it added from the shared catalog), and the skills
other accounts published to the shared catalog (``publications.SKILLS``) that
it holds no copy of.

- :func:`skills_listing`: every skill the account sees, as a card: its name,
  its description and facts (``license``, ``compatibility``, the author and
  version its ``metadata`` gives), its other files, what it serves (the kinds
  of node whose templates name one of its ``curio-behaviors``, and its
  ``curio-features``), whether every call holds it (``core``: the preamble
  Curio's agents read places it), whose it is and whether it is published,
  and the agents that use it, after the account's changes.
- :func:`skill_text`: one skill's body as an agent reads it, and its files.
- :func:`agent_skill_rows`: one agent's skills as its details list them: the
  core skills its preamble holds, those its manifest names after the
  account's changes, and those its instruction or a capability of it names
  as its own; which the account may remove, and which it may add.
- :func:`add_skill`, :func:`remove_skill` and :func:`restore_skills`: the
  account's changes (``infrastructure/agent_skills.py``), each checked. A run
  reads them when it starts (``skill_runs.account_choice``), so its catalog
  and the skills it is handed follow them. Adding a skill of the shared
  catalog copies it into the account's skills first, as adding a published
  agent copies it (``catalog._copy_published``), so it keeps working after
  its publisher unpublishes it.
- :func:`run_skills`: the skills a chat of one attachment lists, which ``/``
  in its composer offers.

Importing, exporting, publishing and removing an account's own skills is
``skill_lifecycle.py``'s.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from utk_curio.backend.app.agents.application import catalog
from utk_curio.backend.app.agents.application import skill_runs
from utk_curio.backend.app.agents.application import spec_reads
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application.turns import prompts
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.domain.manifest import AgentManifest, version_order
from utk_curio.backend.app.agents.infrastructure import agent_skills as agent_skill_store
from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.repositories import user_skills
from utk_curio.backend.app.packages import service as packages_services

log = logging.getLogger(__name__)

#: The keys of a skill's ``metadata`` that name its author and version.
AUTHOR_KEY = "author"
VERSION_KEY = "version"
#: Whose a skill is, as its card says: Curio's, one the account imported, or
#: one of the shared catalog's (published, or the account's copy of one).
CURIO = "curio"
YOURS = "yours"
SHARED = "shared"


# --- The skills an account sees ------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    """The skills an account sees, by name, each kind in its listing's order."""

    #: The skills Curio ships.
    shipped: dict
    #: The skills it holds of its own: those it imported, and its copies of
    #: the shared catalog's.
    own: dict
    #: The shared catalog's skills it holds no copy of.
    published: dict

    @property
    def usable(self) -> dict:
        """The skills an agent of the account may hold: Curio's, then its own."""
        return {**self.shipped, **self.own}

    def find(self, name) -> skill_format.Skill | None:
        if not isinstance(name, str):
            return None
        return self.shipped.get(name) or self.own.get(name) or self.published.get(name)


def published_skills(taken=()) -> dict:
    """The skills of the shared catalog, read leniently, by name, but those
    whose names are in *taken*. One that cannot be read, or whose name is not
    its folder's, is left out and logged."""
    taken = set(taken)
    found: dict = {}
    for name in publications.SKILLS.names():
        if name in taken:
            continue
        folder = publications.SKILLS.entry_dir(name)
        try:
            skill = skill_format.parse(folder, strict=False)
        except (OSError, ValueError) as exc:
            log.warning("The shared catalog's skill %s cannot be read: %s", name, exc)
            continue
        if skill.name == name:
            found[name] = skill
    return found


def seen_skills(user_key: str | None) -> Seen:
    """The skills the account *user_key* sees (:class:`Seen`)."""
    shipped = skill_runs.shipped_skills()
    own = skill_runs.account_skills(user_key)
    return Seen(shipped=shipped, own=own, published=published_skills((*shipped, *own)))


def _source(seen: Seen, name: str) -> str:
    """Whose the skill *name* is (:data:`CURIO`, :data:`YOURS`, :data:`SHARED`)."""
    if name in seen.shipped:
        return CURIO
    if name in seen.own and not user_skills.is_copy(seen.own[name].folder):
        return YOURS
    return SHARED


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


def held_by(user_key: str, m: AgentManifest, seen: Seen) -> _Held:
    """What the agent *m* holds for the account *user_key* (:class:`_Held`),
    of the skills the account sees (*seen*)."""
    usable = seen.usable
    placed = skill_runs.placed_in(prompts._resolve_prompt_text(user_key, m.dir_name, "system"), seen.shipped)
    choice = skill_runs.account_choice(user_key, m)
    own = [skill for skill in skill_runs.agent_skills(m, seen.shipped, choice=choice, usable=usable)
           if skill.name not in placed]
    chat = [name for name in dict.fromkeys(m.instruction_skills) if name in usable and name not in placed]
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


def changeable_agent(user_key: str, coord: object) -> AgentManifest:
    """The agent at *coord*, refused unless the account may change its
    skills (an import review's pick is checked so before anything is kept)."""
    if not isinstance(coord, str):
        raise AgentServiceError(f"{coord!r} is no agent's coordinate", 400)
    m = _require_agent(user_key, coord)
    _require_changeable(user_key, m)
    return m


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
    """Every skill the account sees, as the Agent Catalog shows it (the
    module's docstring says what each card holds): Curio's in its folder's
    order, then the account's own, then the shared catalog's, each by name."""
    seen = seen_skills(user_key)
    core = skill_runs.placed_in(builtin.read_page(builtin.PREAMBLE_FILE, wanted_by="the skills listing"),
                                seen.shipped)
    behaviors_by_template = packages_services.catalog_template_behaviors()
    labels = packages_services.catalog_template_labels()
    every = {**seen.shipped, **dict(sorted(seen.own.items())), **dict(sorted(seen.published.items()))}
    users: dict[str, list[dict]] = {name: [] for name in every}
    for m in _agents(user_key):
        held = held_by(user_key, m, seen)
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
    cards = []
    for name, skill in every.items():
        source = _source(seen, name)
        published = source != CURIO and publications.SKILLS.is_published(name)
        published_by_you = published and publications.SKILLS.is_publisher(name, user_key)
        cards.append({
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
            "source": source,
            "published": published,
            "publishedByYou": published_by_you,
            "publishable": source == YOURS and (not published or published_by_you),
            "removable": name in seen.own,
            "agents": users[name],
        })
    return cards


def skill_text(user_key: str | None, name: str) -> dict:
    """The skill *name* the account sees: its body as an agent reads it,
    its frontmatter left out (a skill Curio ships with its markers filled,
    any other as written), and its other files."""
    skill = seen_skills(user_key).find(name)
    if skill is None:
        raise AgentServiceError(f"Curio ships no skill named {name}, and you see none by that name", 404)
    return {"name": skill.name, "text": skill_runs.text_of(skill), "files": list(skill.files)}


# --- One agent's skills ----------------------------------------------------------------


def agent_skill_rows(user_key: str, coord: str, *, editable: bool = True) -> dict:
    """The skills of the agent at *coord*, as its details list them: each
    ``{name, description, core, added, chat, modes, asked, removable}``
    (:class:`_Held` says what ``chat``, ``modes`` and ``asked`` are), the
    core skills its preamble holds first, then its own in its order, then
    those only its instruction names, then those only its capabilities name;
    ``addable``, the skills it does not hold, Curio's, the account's own,
    then the shared catalog's; and ``changed``, whether the account changed
    them, which Restore undoes. Only a skill its runs hold whatever its
    skills are is not ``removable``."""
    m = _require_agent(user_key, coord)
    seen = seen_skills(user_key)
    usable = seen.usable
    held = held_by(user_key, m, seen)
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

    rows = [row(seen.shipped[name], core=True) for name in seen.shipped if name in held.placed]
    rows += [row(skill) for skill in held.own]
    listed = {entry["name"] for entry in rows}
    for name in dict.fromkeys([*held.chat, *held.modes, *held.asked]):
        if name in usable and name not in listed:
            rows.append(row(usable[name]))
            listed.add(name)
    offered = {**usable, **dict(sorted(seen.published.items()))}
    return {
        "coord": m.dir_name,
        "agentId": m.agent_id,
        "skills": rows,
        "addable": [
            {"name": name, "description": skill.description}
            for name, skill in offered.items() if changeable and name not in listed
        ],
        "changed": bool(choice),
        "editable": changeable,
    }


def _usable_name(user_key: str, name: object, seen: Seen) -> str:
    """*name*, a skill an agent of the account may hold: Curio's, the
    account's own, or the shared catalog's, which is copied into the
    account's skills first (:func:`_copy_published`). The account's copy of
    one is replaced when the publication's version is newer, as a copy of a
    published agent is when it is added again."""
    if not isinstance(name, str) or seen.find(name) is None:
        raise AgentServiceError(f"Curio ships no skill named {name}, and you see none by that name", 404)
    if name in seen.published:
        _copy_published(user_key, name)
    elif name in seen.own and user_skills.is_copy(seen.own[name].folder):
        held = seen.own[name].metadata.get(VERSION_KEY)
        if held:
            _copy_published(user_key, name, newer_than=held)
    return name


def _copy_published(user_key: str, name: str, *, newer_than: str | None = None) -> None:
    """Copy the shared catalog's skill *name* into the account's skills,
    marked as a copy (``user_skills.is_copy``), as adding a published agent
    copies it (``catalog._copy_published``): it keeps working after its
    publisher unpublishes it, and it is never this account's to publish.

    With *newer_than*, the version of the account's copy, the publication
    replaces that copy only when its own version is newer."""
    if not publications.SKILLS.is_published(name):
        return
    folder = publications.SKILLS.entry_dir(name)
    if newer_than is not None:
        try:
            version = skill_format.parse(folder, strict=False).metadata.get(VERSION_KEY)
        except (OSError, ValueError):
            return
        if not version or version_order(version) <= version_order(newer_than):
            return
    try:
        user_skills.write(user_key, name, user_skills.read_files(folder), copied=True,
                          replace=newer_than is not None)
    except FileExistsError:
        pass  # a concurrent add wrote it first


def add_skill(user_key: str, coord: str, name: object) -> dict:
    """Add the skill *name* to the agent at *coord*, for the account: a
    skill its manifest left out, or one the account removed. One its
    preamble holds is refused; one it holds already changes nothing."""
    m = _require_agent(user_key, coord)
    _require_changeable(user_key, m)
    seen = seen_skills(user_key)
    if isinstance(name, str) and name in seen.shipped and name in held_by(user_key, m, seen).placed:
        raise AgentServiceError(f"{m.name} holds {name} in every call already", 400)
    name = _usable_name(user_key, name, seen)
    named = {skill.name for skill in skill_runs.agent_skills(m, seen.shipped, usable=seen.usable)}

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
    seen = seen_skills(user_key)
    if not isinstance(name, str) or name not in seen.usable:
        raise AgentServiceError(f"Curio ships no skill named {name}, and you hold none by that name", 404)
    held = held_by(user_key, m, seen)
    always = why_always(held, name, m.name)
    if always:
        raise AgentServiceError(always, 400)
    if all(skill.name != name for skill in held.own):
        raise AgentServiceError(f"{m.name} has no skill {name}", 404)
    named = {skill.name for skill in skill_runs.agent_skills(m, seen.shipped, usable=seen.usable)}

    def change(current: agent_skill_store.SkillChoice) -> agent_skill_store.SkillChoice:
        added = tuple(skill for skill in current.added if skill != name)
        removed = current.removed if name not in named or name in current.removed else (*current.removed, name)
        return agent_skill_store.SkillChoice(added=added, removed=removed)

    _store_update(user_key, m, change)
    return agent_skill_rows(user_key, coord)


def why_always(held: _Held, name: str, agent_name: str) -> str | None:
    """Why the agent *agent_name*, holding *held*, holds the skill *name*
    whatever its skills are, so it cannot lose it, or None."""
    if name in held.placed:
        return f"{name} is in every call of {agent_name}, so it cannot be removed"
    if name in held.chat:
        return f"{name} is always held by the chat of {agent_name}, so it cannot be removed"
    if name in held.modes:
        return f"{name} is always held by {', '.join(held.modes[name])} of {agent_name}, so it cannot be removed"
    if name in held.asked:
        return f"{name} is always held when another agent asks {agent_name} for its work, so it cannot be removed"
    return None


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
