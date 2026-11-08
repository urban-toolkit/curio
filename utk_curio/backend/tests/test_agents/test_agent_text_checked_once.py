"""A page of Curio's agent text is checked once, not at each lookup.

``agent_text.page_file`` finds the file of a page of the base entry, as
``curio:<path>`` names it, and refuses one that leads out of the base entry.
It resolved the file and the base entry at every call: two walks of every
component of both paths, with an lstat each, letting the GIL go at each one.
Every lookup of an agent's manifest checks its ``curio:`` prompts through it,
and a run reads its pages' sections through it. With 100 agent turns at once
(``tests/stress``, run 42528241074 of the stage with agents), the GIL's holder
was in ``page_file`` in 9.0% of py-spy's samples.

So the check runs once per base entry and page: the base entry is a folder
Curio ships, which the backend renders when it starts and reads as it was
then. Under ``curio.py start --dev`` (``CURIO_DEV=1``), where a read renders a
page again, the check runs again too.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""
from __future__ import annotations

import pathlib
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
#: The base entry: the pages every agent Curio ships reads.
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
#: A page the base entry lists, in a folder of its own.
RULES_PAGE = "rules/plan-rules.md"


def _resolves(monkeypatch) -> list:
    """The paths resolved from now on."""
    resolved: list = []
    original = pathlib.Path.resolve

    def counted(self, *args, **kwargs):
        resolved.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "resolve", counted)
    return resolved


def _user_manifest(system: str) -> dict:
    """An account's agent whose preamble is *system*."""
    return {
        "id": "agent.test.my-checker",
        "name": "My Checker",
        "category": "node",
        "version": "1.0.0",
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "compatibleTargets": [{"kind": "node", "requires": []}],
        "prompts": {
            "system": {"path": system, "variables": []},
            "instruction": {"path": "prompts/instruction.md", "variables": []},
        },
        "provenance": {"publisher": "karla"},
    }


def _leading_out(base: Path, page: str, tmp_path: Path) -> None:
    """Make *page* of the base entry *base* a symbolic link to a file outside it."""
    outside = tmp_path / "secret.md"
    outside.write_text("Not agent text.\n", encoding="utf-8")
    (base / page).unlink()
    (base / page).symlink_to(outside)


def test_a_page_is_found_again_without_walking_its_path(monkeypatch):
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    first = agent_text.page_file(RULES_PAGE)
    resolved = _resolves(monkeypatch)

    again = agent_text.page_file(RULES_PAGE)
    walks = list(resolved)

    assert again == first == agent_text.base_dir() / RULES_PAGE
    assert walks == [], f"page_file walked {walks} again"


def test_a_manifest_and_a_runs_sections_find_their_pages_without_a_walk(monkeypatch):
    """What a turn asks many times: a manifest's ``curio:`` preamble, checked
    at each parse, and the sections of the pages a run is composed from."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin
    from utk_curio.backend.app.agents.domain.manifest import parse_agent_manifest

    monkeypatch.delenv("CURIO_DEV", raising=False)
    manifest = _user_manifest(f"curio:{builtin.PREAMBLE_FILE}")
    parse_agent_manifest(manifest)
    tools = agent_text.sections(builtin.TOOLS_FILE)
    resolved = _resolves(monkeypatch)

    system = parse_agent_manifest(manifest).prompts["system"]
    again = agent_text.sections(builtin.TOOLS_FILE)
    walks = list(resolved)

    assert system.shared == builtin.PREAMBLE_FILE
    assert again == tools and again
    assert walks == [], f"a parse and a page's sections walked {walks}"


def test_a_page_checked_in_one_base_entry_is_checked_anew_in_another(tmp_path, monkeypatch):
    """The check is kept per base entry: a copy whose page leads out is
    refused, though the same page of the shipped base entry passed."""
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    agent_text.page_file(RULES_PAGE)
    copy = tmp_path / BASE.name
    shutil.copytree(BASE, copy)
    _leading_out(copy, RULES_PAGE, tmp_path)
    monkeypatch.setattr(agent_text, "base_dir", lambda: copy)

    with pytest.raises(agent_text.AgentTextError, match="leads out"):
        agent_text.page_file(RULES_PAGE)


def test_under_dev_a_page_that_now_leads_out_is_refused_at_once(tmp_path, monkeypatch):
    """``curio.py start --dev`` reads each page as it is now, so a page made a
    link out of the base entry is refused at its next lookup."""
    from utk_curio.backend.app.agents.domain import agent_text

    copy = tmp_path / BASE.name
    shutil.copytree(BASE, copy)
    monkeypatch.setattr(agent_text, "base_dir", lambda: copy)
    monkeypatch.setenv("CURIO_DEV", "1")
    assert agent_text.page_file(RULES_PAGE) == copy / RULES_PAGE
    _leading_out(copy, RULES_PAGE, tmp_path)

    with pytest.raises(agent_text.AgentTextError, match="leads out"):
        agent_text.page_file(RULES_PAGE)
