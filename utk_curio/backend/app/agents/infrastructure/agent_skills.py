"""The skills an account added to an agent or removed from it.

One owner-only file per account, ``.curio/users/<key>/agent-skills.json``,
beside ``llm-configs.json`` and written the same way (``common.owner_only_file``:
0600 in a 0700 directory, atomic writes under the two-layer lock)::

    {"version": 1,
     "agents": {"<agentId>": {"added": ["<skill>", ...], "removed": ["<skill>", ...]}}}

An entry is keyed by the agent's id before ``@``, as the model chosen for it is
(``llm_configs``), so one change covers every version of the agent and every
project. ``added`` are skills its manifest does not name, in the order they
were added; ``removed`` are skills its manifest names that its runs go without.
An agent with no entry holds the skills its manifest names, and nothing about a
change goes into a project, so a shared project never carries one.

Which skills a change may name is the application's to check
(``application/skill_catalog.py``); this store keeps skill names only, each
one a skill's name as the Agent Skills format has it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.common import owner_only_file
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

log = logging.getLogger(__name__)

STORE_FILENAME = "agent-skills.json"
STORE_VERSION = 1
_LOCK_NAMESPACE = "agent-skills"


class AgentSkillsError(ValueError):
    """A store that cannot be read, with the HTTP status it answers with."""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SkillChoice:
    """What an account changed of one agent's skills."""

    #: Skills its manifest does not name, in the order they were added.
    added: tuple[str, ...] = ()
    #: Skills its manifest names that its runs go without.
    removed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed)

    def as_entry(self) -> dict:
        return {"added": list(self.added), "removed": list(self.removed)}


def _names(value) -> tuple[str, ...]:
    """The skill names of a stored list, each once, in its order; anything
    that is no skill's name is left out."""
    found: list[str] = []
    for name in value if isinstance(value, list) else ():
        if skill_format.is_name(name) and name not in found:
            found.append(name)
    return tuple(found)


def _choice(entry) -> SkillChoice:
    if not isinstance(entry, dict):
        return SkillChoice()
    return SkillChoice(added=_names(entry.get("added")), removed=_names(entry.get("removed")))


class AgentSkillStore:
    """File-backed store of one account's changes to its agents' skills."""

    def __init__(self, base: Path | None = None):
        self._base = base

    def _user_dir(self, user_key: str) -> Path:
        base = self._base if self._base is not None else users_base()
        return base / user_key_segment(user_key)

    def path(self, user_key: str) -> Path:
        return self._user_dir(user_key) / STORE_FILENAME

    def _locked(self, user_key: str):
        return owner_only_file.locked(
            self._user_dir(user_key), STORE_FILENAME, namespace=_LOCK_NAMESPACE, key=user_key
        )

    def read(self, user_key: str) -> dict[str, SkillChoice]:
        """Every agent's change, by agent id; none when the account has no
        file. An unreadable file is an error, never an empty store, so a
        change is never lost to a write that started from nothing."""
        path = self.path(user_key)
        if not path.is_file():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("agent-skills store for %s is unreadable (%s)", user_key, exc.__class__.__name__)
            raise AgentSkillsError("the file of your agents' skills is unreadable")
        agents = doc.get("agents") if isinstance(doc, dict) else None
        if not isinstance(agents, dict):
            raise AgentSkillsError("the file of your agents' skills is malformed")
        found = {agent_id: _choice(entry) for agent_id, entry in agents.items() if isinstance(agent_id, str)}
        return {agent_id: choice for agent_id, choice in found.items() if choice}

    def choice(self, user_key: str, agent_id: str) -> SkillChoice:
        """What the account changed of the skills of *agent_id*."""
        return self.read(user_key).get(agent_id, SkillChoice())

    def update(self, user_key: str, agent_id: str,
               change: Callable[[SkillChoice], SkillChoice]) -> SkillChoice:
        """Replace the change of *agent_id* with ``change(current)``, read and
        written under the lock, and return it. An empty change removes the
        agent's entry."""
        with self._locked(user_key):
            choices = self.read(user_key)
            updated = change(choices.get(agent_id, SkillChoice()))
            if updated:
                choices[agent_id] = SkillChoice(added=_names(list(updated.added)),
                                                removed=_names(list(updated.removed)))
            else:
                choices.pop(agent_id, None)
            self._write(user_key, choices)
            return choices.get(agent_id, SkillChoice())

    def clear(self, user_key: str, agent_id: str) -> None:
        """Drop the change of *agent_id*: its runs hold its manifest's skills."""
        self.update(user_key, agent_id, lambda _current: SkillChoice())

    def _write(self, user_key: str, choices: dict[str, SkillChoice]) -> None:
        doc = {
            "version": STORE_VERSION,
            "agents": {agent_id: choice.as_entry() for agent_id, choice in sorted(choices.items())},
        }
        owner_only_file.write_json(self.path(user_key), doc)


_default_store: AgentSkillStore | None = None


def default_store() -> AgentSkillStore:
    global _default_store
    if _default_store is None:
        _default_store = AgentSkillStore()
    return _default_store
