"""The green run of a git tree, for a push to main that would test it again.

A Full stack build run whose every job passed uploads an artifact named after
the git tree it tested (``tested-tree-<tree>``, ci-report's step). For a PR
run that is the tree of the PR's merge ref: the PR merged into main as it was.
When the PR then merges with nothing landed on main in between, main's merge
commit has that same tree, and its run would test the same files with the same
tests a second time. On a push to main, pick-runners asks this script for such
a run, and the test jobs skip when it names one.

    python3 scripts/ci_tested_tree.py lookup <tree>

prints ``run=<id>`` and ``url=<link>`` for $GITHUB_OUTPUT when a green run of
the tree exists, and nothing otherwise. Any error also prints nothing, with a
warning: the run then tests everything, as it would have without this.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

ARTIFACT_PREFIX = "tested-tree-"
TREE = re.compile(r"^[0-9a-f]{40}$")


def artifact_name(tree: str) -> str:
    if not TREE.match(tree):
        raise ValueError(f"not a git tree id: {tree!r}")
    return ARTIFACT_PREFIX + tree


def _get(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def green_run(tree: str, fetch, this_run: str = "") -> dict | None:
    """The newest run with an unexpired ``tested-tree-<tree>`` artifact, other than this one.

    ``fetch(path)`` answers a GitHub API path, as ``_get`` does.
    """
    found = fetch(f"actions/artifacts?name={artifact_name(tree)}&per_page=20")
    runs = [artifact.get("workflow_run") or {} for artifact in found.get("artifacts", [])
            if not artifact.get("expired")]
    runs = [run for run in runs if run.get("id") and str(run["id"]) != str(this_run)]
    return max(runs, key=lambda run: run["id"]) if runs else None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "lookup":
        print(__doc__, file=sys.stderr)
        return 2
    tree = argv[1]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    try:
        run = green_run(tree, lambda path: _get(f"{api}/repos/{repo}/{path}", token),
                        os.environ.get("GITHUB_RUN_ID", ""))
    except Exception as exc:  # the run tests everything instead
        print(f"::warning::could not look up a green run of tree {tree}: {exc}", file=sys.stderr)
        return 0
    if run:
        print(f"run={run['id']}")
        print(f"url={server}/{repo}/actions/runs/{run['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
