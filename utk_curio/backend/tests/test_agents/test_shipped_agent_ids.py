"""No app code picks a shipped agent by its id.

Curio finds an agent by the capabilities its manifest declares: the one that
writes a node's content declares ``node.content.generate``, the one that finds
datasets ``dataset.discover``, and so on. A user's own agent that declares the
same capability is then picked where a shipped one would be. An id in app code
is a place where it is not, so the scan covers the backend app and the
frontend source, comments included.

The roster that defines the shipped agents is their folders in ``agents/``,
beside ``utk_curio/``, and the loader in ``agents/domain/builtin.py`` names
none of them. One place names them on purpose: the offline evaluation library
under ``agents/evaluation/``, which reconstructs runs of one named agent.
Tests may name them too.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from utk_curio.backend.app.agents.domain import builtin

REPO_ROOT = Path(__file__).resolve().parents[4]
#: Each scanned tree, with the files and folders in it that may name a shipped agent.
SCANNED = (
    (
        "utk_curio/backend/app",
        set(),
        {"utk_curio/backend/app/agents/evaluation"},
    ),
    (
        "utk_curio/frontend/urban-workflows/src",
        set(),
        {"utk_curio/frontend/urban-workflows/src/tests"},
    ),
)
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache"}


def _shipped_ids() -> set[str]:
    return {m.agent_id for m in builtin.list_builtin_manifests()}


def _pattern(agent_id: str) -> re.Pattern:
    """*agent_id* as a whole id: ``agent.curio.node-builder`` or ``agent.curio.node-builder@1``,
    never part of a longer id such as ``agent.curio.node-builder-copy``."""
    return re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(agent_id) + r"(?![A-Za-z0-9_-])")


def test_the_scan_knows_every_shipped_agent():
    ids = _shipped_ids()
    # The four cards and the three helpers; a roster the scan cannot read
    # would make it pass on nothing.
    assert {"agent.curio.node-builder", "agent.curio.dataset-finder", "agent.curio.dataflow-builder",
            "agent.curio.researcher"} <= ids
    assert _pattern("agent.curio.node-builder").search('coord="agent.curio.node-builder@1"')
    assert not _pattern("agent.curio.node-builder").search("agent.curio.node-builder-copy")


def test_no_app_code_names_a_shipped_agent():
    ids = _shipped_ids()
    patterns = {agent_id: _pattern(agent_id) for agent_id in ids}
    found = []
    for tree, allowed_files, allowed_dirs in SCANNED:
        root = REPO_ROOT / tree
        files = 0
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS
                and (here / d).relative_to(REPO_ROOT).as_posix() not in allowed_dirs
            ]
            for filename in filenames:
                path = here / filename
                relative = path.relative_to(REPO_ROOT).as_posix()
                if relative in allowed_files:
                    continue
                files += 1
                data = path.read_bytes()
                if not any(agent_id.encode() in data for agent_id in ids):
                    continue
                lines = data.decode("utf-8", errors="replace").splitlines()
                for number, line in enumerate(lines, 1):
                    for agent_id, pattern in patterns.items():
                        if pattern.search(line):
                            found.append(f"{relative}:{number}: {agent_id}")
        # Guards the walk itself: a missing tree would make the scan a vacuous pass.
        assert files > 0, f"no files under {root}"

    assert not found, (
        "app code names a shipped agent; find the agent by the capability it "
        "declares instead (or name it in words in a comment):\n" + "\n".join(found)
    )
