"""Node code never sees this Curio's own LLM endpoint, the backend's own secrets or the sandbox's token.

The sandbox server runs node code in its own process (isolation off, a local
launch's default) and forks every isolated child from a zygote that inherits
its environment. So the launcher starts it (``cli/services.start_sandbox``)
without the variables that hold the deployment's key and URL, or the path of
the file that holds them, and without the backend's own secrets: the key its
sessions are signed with and its database's address
(``common/llm_endpoint.BACKEND_ONLY_VARIABLES``). The sandbox holds its own
token, which opens its routes; the zygote and every JavaScript run's Node start
without it (``common/llm_endpoint.for_node_code``).

Fake values only: no real host or key belongs in a test.
"""

import io
import json
import os
import subprocess
import sys
import textwrap
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

DROPPED = {
    "CURIO_DEFAULT_LLM_API_KEY": "fake-deployment-key-0001",
    "CURIO_DEFAULT_LLM_BASE_URL": "https://llm.example.test/v1",
    "GUEST_LLM_API_KEY": "fake-guest-key-0002",
    "GUEST_LLM_BASE_URL": "https://guest.llm.example.test/v1",
    "CURIO_DEFAULT_LLM_ENDPOINT_FILE": "/run/secrets/fake-llm-endpoint",
}

#: Runs one node in the sandbox's in-process worker, in a process started with
#: the sandbox server's environment, and prints what the node saw.
NODE_RUN = textwrap.dedent("""
    import json, sys
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    names = json.loads(sys.argv[1])
    code = (
        "    import json, os\\n"
        f"    names = {names!r}\\n"
        "    held = sorted(name for name in names if name in os.environ)\\n"
        "    print('HELD ' + json.dumps(held))\\n"
        "    print('TEXT ' + json.dumps(json.dumps(dict(os.environ))))\\n"
        "    return len(held)\\n"
    )
    result = execute_code(code, "", "PYTHON_COMPUTATION", "", save_dataset=False)
    print("RESULT " + json.dumps({"stdout": result["stdout"], "stderr": result["stderr"]}))
""")


def _sandbox_launch_environment(monkeypatch):
    """The environment the launcher starts the sandbox server with, no
    process started."""
    from utk_curio.cli import services

    started = {}

    class _Started:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = None

        def poll(self):
            return 0

    def popen(args, **kwargs):
        started["env"] = kwargs["env"]
        return _Started()

    monkeypatch.setattr(services, "subprocess", types.SimpleNamespace(
        Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(services, "_kill_port", lambda port: None)
    monkeypatch.setattr(services, "_skip_dep_install", lambda: True)
    services.start_sandbox("127.0.0.1", 2999)
    return started["env"]


def test_the_sandbox_starts_without_the_deployments_llm_endpoint(monkeypatch):
    for name, value in DROPPED.items():
        monkeypatch.setenv(name, value)

    env = _sandbox_launch_environment(monkeypatch)

    assert [name for name in DROPPED if name in env] == []
    text = json.dumps(env)
    assert not [value for value in DROPPED.values() if value in text]
    # Everything else still reaches it.
    assert env["PATH"] == os.environ["PATH"]


#: The backend's own secrets: the key its sessions are signed with, and its
#: database's address, which for Postgres carries the password. No sandbox
#: code reads them, and a JavaScript node has network.
BACKENDS_OWN = {
    "SECRET_KEY": "fake-secret-key-0003",
    "DATABASE_URL": "postgresql://curio:fake-password-0004@db.example.test/curio",
    "DATABASE_URL_TEST": "postgresql://curio:fake-password-0005@db.example.test/curio_test",
}

#: The sandbox's token in the test below.
SANDBOX_TOKEN = "fake-sandbox-token-0001"


def test_the_sandbox_starts_without_the_backends_own_secrets(monkeypatch):
    for name, value in BACKENDS_OWN.items():
        monkeypatch.setenv(name, value)

    env = _sandbox_launch_environment(monkeypatch)

    assert [name for name in BACKENDS_OWN if name in env] == []
    text = json.dumps(env)
    assert not [value for value in BACKENDS_OWN.values() if value in text]
    assert env["PATH"] == os.environ["PATH"]


def test_neither_nodes_environment_nor_the_zygotes_holds_the_sandboxs_token(monkeypatch):
    """``node_env`` and ``zygote_environment`` copied the sandbox's environment
    whole, its token among them, so every JavaScript node and every isolated
    child held it, and with it every sandbox route. One scrub builds both:
    the token reaches neither, by its name or by its value, whether they start
    from the sandbox's environment or from one they are given, and the rest of
    the environment still does."""
    from utk_curio.sandbox.isolation import lifecycle, supervisor
    from utk_curio.sandbox.util import node_runtime

    # The suite's conftest takes the token out of the environment for every
    # test: put one back, or there would be nothing to scrub.
    monkeypatch.setenv("CURIO_SANDBOX_TOKEN", SANDBOX_TOKEN)
    assert os.environ["CURIO_SANDBOX_TOKEN"] == SANDBOX_TOKEN
    given = {"PATH": os.environ.get("PATH", ""), "CURIO_SANDBOX_TOKEN": SANDBOX_TOKEN}
    limits = dict(supervisor.DEFAULT_LIMITS)
    built = {
        "node_env()": node_runtime.node_env(),
        "node_env(base=...)": node_runtime.node_env(base=given),
        "zygote_environment()": lifecycle.zygote_environment(limits),
        "zygote_environment(environ=...)": lifecycle.zygote_environment(limits, environ=given),
    }
    for name, env in built.items():
        assert "CURIO_SANDBOX_TOKEN" not in env, f"{name} holds CURIO_SANDBOX_TOKEN"
        assert SANDBOX_TOKEN not in env.values(), f"{name} holds the token under another name"
        assert env.get("PATH") == given["PATH"], f"{name} lost the rest of the environment"


def test_node_code_finds_none_of_it_in_its_environment(monkeypatch, tmp_path):
    for name, value in DROPPED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    env = _sandbox_launch_environment(monkeypatch)

    done = subprocess.run(
        [sys.executable, "-c", NODE_RUN, json.dumps(sorted(DROPPED))],
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
    assert not [value for value in DROPPED.values() if value in seen[0]]
