"""No test names a retired built-in agent (#489).

#417 folded the Node Explainer and the Debug Agent into Chat, and their ids
left the roster in ``agents/domain/builtin.py``. Test fixtures went on using
both ids until #549 gave them plainly made-up ones (``agent.my-explainer``,
``agent.my-debugger``). A fixture with a retired id reads as a test of an
agent Curio no longer has, so the scan covers the backend and frontend test
trees.
"""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.agents.domain import builtin

REPO_ROOT = Path(__file__).resolve().parents[4]
TEST_TREES = (
    "utk_curio/backend/tests",
    "utk_curio/frontend/urban-workflows/src/tests",
)
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache"}
# Each retired id, built from parts so this file does not match itself, and
# the built-in that took over its work.
RETIRED = {
    "agent." + "node-explainer": "agent.chat-agent",
    "agent." + "debug-agent": "agent.chat-agent",
}


def _live_ids() -> set[str]:
    return {spec.agent_id for spec in builtin.BUILTIN_AGENTS}


def test_the_retired_ids_are_off_the_roster():
    live = _live_ids()
    back = sorted(set(RETIRED) & live)
    assert not back, f"{back} are built-ins again: take them off RETIRED"
    for retired, successor in RETIRED.items():
        assert successor in live, f"{successor}, which took over {retired}, is not a built-in"


def test_no_test_names_a_retired_agent():
    found = []
    for tree in TEST_TREES:
        root = REPO_ROOT / tree
        files = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                files += 1
                data = path.read_bytes()
                if not any(retired.encode() in data for retired in RETIRED):
                    continue
                lines = data.decode("utf-8", errors="replace").splitlines()
                for number, line in enumerate(lines, 1):
                    for retired in RETIRED:
                        if retired in line:
                            found.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {retired}")
        # Guards the walk itself: a missing tree would make the scan a vacuous pass.
        assert files > 0, f"no files under {root}"

    assert not found, (
        f"tests name retired agents ({', '.join(RETIRED)}); the built-ins are "
        f"{', '.join(sorted(_live_ids()))}. Use a made-up id such as agent.my-explainer:\n"
        + "\n".join(found)
    )
