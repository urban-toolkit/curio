"""Node code never holds the secret the backend processes of a start show each other.

``curio.py start --backend-processes N`` makes a secret at each start, which
its backend processes show each other on their calls to one another
(``cli/backend_group.py``, ``backend/app/collaboration/owner_calls.py``). It is
in each backend's environment and in no other: the sandbox, whose zygote and
Node runs start node code, starts without it, so node code finds it nowhere in
its environment, by name or by value, even when the launcher's own
environment held an older one.

The backends start faked (``backend/tests/_support/backend_group_fakes.py``);
the sandbox's environment is the one the launcher builds, and the node runs in
the sandbox's in-process worker, in a process started with that environment.
Fake values only.
"""

import json
import subprocess
import sys

from .test_sandbox_llm_environment import NODE_RUN, REPO_ROOT, _sandbox_launch_environment

#: A secret an earlier start, or an outer shell, left in the launcher's environment.
OLDER = "fake-older-backend-token-0006"


def test_node_code_never_holds_the_secret_the_backends_of_a_start_share(monkeypatch, tmp_path):
    from utk_curio.backend.tests._support.backend_group_fakes import boot

    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", OLDER)
    booted = boot(monkeypatch, processes=2)
    secret = booted.env(0)["CURIO_BACKEND_TOKEN"]
    assert secret and secret != OLDER, "the start made no secret of its own"
    assert booted.env(1)["CURIO_BACKEND_TOKEN"] == secret

    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    env = _sandbox_launch_environment(monkeypatch)
    text = json.dumps(env)
    assert "CURIO_BACKEND_TOKEN" not in env, "the sandbox starts with a backend's secret"
    assert secret not in text and OLDER not in text, "the sandbox's environment holds a backend's secret"

    done = subprocess.run(
        [sys.executable, "-c", NODE_RUN, json.dumps(["CURIO_BACKEND_TOKEN"])],
        cwd=REPO_ROOT, env={**env, "PYTHONPATH": REPO_ROOT},
        capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    )
    result = json.loads(lines[-1][len("RESULT "):])
    stdout = result["stdout"]
    assert result["stderr"] == "", result["stderr"]
    held = [json.loads(line[len("HELD "):]) for line in stdout if line.startswith("HELD ")]
    assert held == [[]], stdout
    seen = [json.loads(line[len("TEXT "):]) for line in stdout if line.startswith("TEXT ")]
    assert len(seen) == 1, stdout
    assert secret not in seen[0] and OLDER not in seen[0], "node code found a backend's secret in its environment"
