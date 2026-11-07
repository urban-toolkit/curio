"""A self-hosted runner keeps its workspace between jobs, so no job that can run
on one checks out part of the tree, and each such job clears a checkout of part
of the tree that an earlier job left there before its own checkout.

actions/checkout with ``sparse-checkout`` in non-cone mode sets
``core.sparseCheckout`` in the workspace's ``.git/config``. The next job's
actions/checkout, asked for the whole tree, runs ``git sparse-checkout disable``,
which writes ``false`` into the worktree's config, then turns worktree config
off, so the ``true`` stays and its checkout holds the earlier job's files
alone. On 11-07 the Weekly flake hunt's report left that on arcade-cpu-05, and
every later job there failed at its first local action (start-stack) within
seconds, so the runner took job after job of every run.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: A runner label GitHub hosts; any other label, or an expression, can be a
#: self-hosted runner.
GITHUB_HOSTED = re.compile(r"^(ubuntu|windows|macos)-")
#: The block of a reclaim step that clears what an earlier checkout of part of
#: the tree left: from its ``if`` line to its ``fi``.
CLEARS_SPARSE = re.compile(r"^[ \t]*if \[ -f \.git/config \]; then\n.*?^[ \t]*fi$", re.M | re.S)
#: The file the poisoned workspace's checkout kept, and one it left out, as on
#: arcade-cpu-05: start-stack's action.
KEPT = "scripts/ci_weekly_report.py"
LEFT_OUT = ".github/actions/start-stack/action.yml"


def _jobs():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (workflow.get("jobs") or {}).items():
            yield f"{path.name}: {job_id}", job


def _can_run_self_hosted(job: dict) -> bool:
    runs_on = job.get("runs-on")
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    return any(not GITHUB_HOSTED.match(str(label)) for label in labels)


def _is_checkout(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _clearing_before_checkout(job: dict) -> str:
    """The block that clears a checkout of part of the tree in the steps before
    the job's first checkout, or ``""``."""
    for step in job.get("steps") or []:
        if _is_checkout(step):
            return ""
        found = CLEARS_SPARSE.search(str(step.get("run", "")))
        if found:
            return found.group(0)
    return ""


def test_no_job_that_can_run_on_a_self_hosted_runner_checks_out_part_of_the_tree():
    partial = [name for name, job in _jobs() if _can_run_self_hosted(job)
               for step in job.get("steps") or []
               if _is_checkout(step) and (step.get("with") or {}).get("sparse-checkout")]
    assert not partial, (
        f"{partial} check out part of the tree on a runner that keeps its workspace: every later "
        "job there would check out those files alone"
    )


def test_every_job_that_can_run_on_a_self_hosted_runner_clears_an_earlier_partial_checkout_first():
    blocks = {name: _clearing_before_checkout(job) for name, job in _jobs()
              if _can_run_self_hosted(job) and any(_is_checkout(step) for step in job.get("steps") or [])}
    missing = sorted(name for name, block in blocks.items() if not block)
    assert not missing, f"{missing} do not clear an earlier checkout of part of the tree before their own"
    reclaim = blocks["docker-compose.yml: build-image"]
    differing = sorted(name for name, block in blocks.items() if block.strip() != reclaim.strip())
    assert not differing, f"{differing} clear it otherwise than docker-compose.yml's reclaim step"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
                          env=_git_env(repo))


def _git_env(repo: Path) -> dict:
    """git as on a runner, with no global or system config of this machine's."""
    env = dict(os.environ)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(repo.parent / "gitconfig"),
               GIT_AUTHOR_NAME="ci", GIT_AUTHOR_EMAIL="ci@example.com",
               GIT_COMMITTER_NAME="ci", GIT_COMMITTER_EMAIL="ci@example.com")
    return env


def _poisoned_workspace(tmp_path: Path) -> tuple[Path, str]:
    """A workspace an earlier job checked out part of, as actions/checkout does
    with ``sparse-checkout`` in non-cone mode; and its commit."""
    repo = tmp_path / "workspace"
    for name in (KEPT, LEFT_OUT, "README.md"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tree")
    commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "config", "core.sparseCheckout", "true")
    with open(repo / ".git" / "info" / "sparse-checkout", "a", encoding="utf-8") as patterns:
        patterns.write(f"\n{KEPT}\n")
    _git(repo, "checkout", "--progress", "--force", "-B", "main", commit)
    assert (repo / KEPT).exists() and not (repo / LEFT_OUT).exists(), "the earlier checkout was not partial"
    return repo, commit


def _next_checkout(repo: Path, commit: str) -> None:
    """What actions/checkout runs for a job that asks for the whole tree, in a
    workspace an earlier job left (its log on arcade-cpu-05, 11-07)."""
    _git(repo, "clean", "-ffdx")
    _git(repo, "reset", "--hard", "HEAD")
    _git(repo, "sparse-checkout", "disable")
    _git(repo, "config", "--local", "--unset-all", "extensions.worktreeConfig", check=False)
    _git(repo, "checkout", "--progress", "--force", "-B", "main", commit)


def test_the_next_job_after_a_partial_checkout_checks_out_the_whole_tree(tmp_path):
    """The reclaim step's block, run where the next job's reclaim runs it: in
    the workspace, before actions/checkout."""
    repo, commit = _poisoned_workspace(tmp_path)
    jobs = dict(_jobs())
    block = _clearing_before_checkout(jobs["docker-compose.yml: build-image"])
    subprocess.run(["bash", "-eo", "pipefail", "-c", block or "true"], cwd=repo, check=True,
                   env=_git_env(repo), capture_output=True, text=True)
    _next_checkout(repo, commit)
    assert (repo / LEFT_OUT).exists(), (
        f"the next job's checkout held only the earlier job's files: {LEFT_OUT} is missing, as start-stack "
        "was on arcade-cpu-05"
    )
