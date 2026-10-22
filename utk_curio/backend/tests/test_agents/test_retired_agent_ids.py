"""No test names a retired built-in agent (#489).

#417 folded the Node Explainer and the Debug Agent into Chat, and their ids
left the roster, the folders in ``agents/``. Test fixtures went on using
both ids until #549 gave them plainly made-up ones (``agent.test.my-explainer``,
``agent.test.my-debugger``). A fixture with a retired id reads as a test of an
agent Curio no longer has, so the scan covers the backend and frontend test
trees.

Three more left on 2026-10-14, each taken over by a card that runs its prompt
as a mode: the Node Builder writes node content, the Researcher checks facts,
and the Package Builder recommends packages.

Three more left later that day, when the catalog went down to four cards: the
Researcher took over Chat, and the Node Builder took over the Connection
Builder and the Package Builder. Every id that went to Chat or the Package
Builder now names their successor.

On 2026-10-22 every built-in's id took its publisher, as Discovery source ids
name theirs: ``agent.<name>`` became ``agent.curio.<name>``, with no alias.
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
    "agent." + "node-explainer": "agent.curio.researcher",
    "agent." + "debug-agent": "agent.curio.researcher",
    "agent." + "node-content-builder": "agent.curio.node-builder",
    "agent." + "node-researcher": "agent.curio.researcher",
    "agent." + "package-recommendation": "agent.curio.node-builder",
    "agent." + "chat-agent": "agent.curio.researcher",
    "agent." + "connection-builder": "agent.curio.node-builder",
    "agent." + "package-builder": "agent.curio.node-builder",
    # The ids without a publisher.
    "agent." + "dataflow-builder": "agent.curio.dataflow-builder",
    "agent." + "dataflow-planner": "agent.curio.dataflow-planner",
    "agent." + "dataflow-reader": "agent.curio.dataflow-reader",
    "agent." + "dataset-finder": "agent.curio.dataset-finder",
    "agent." + "generated-content-evaluator": "agent.curio.generated-content-evaluator",
    "agent." + "node-builder": "agent.curio.node-builder",
    "agent." + "researcher": "agent.curio.researcher",
}


def _live_ids() -> set[str]:
    return {m.agent_id for m in builtin.list_builtin_manifests()}


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
        f"{', '.join(sorted(_live_ids()))}. Use a made-up id such as agent.test.my-explainer:\n"
        + "\n".join(found)
    )
