"""An editor's run reads the node libraries of the dataflow's owner too.

Under fork isolation each account's node libraries are a folder of its own
(``supervisor.user_overlay_dir``, #332), which the child puts on its import
path. A run of an editor the dataflow's owner invited names her storage key in
the ``library_keys`` of ``/exec`` (the backend's ``node_exec.library_keys_of``,
which alone decides it). The request then names his folder, then hers, which
the run only locates and never writes. A run that names no other account, the
owner's own or anyone else's, names its own folder alone, as before. A key that
is no plain storage key, and the run's own, are left out.

Everything up to the zygote is real; the zygote is a fake that keeps the
request it is handed, and the child's manifest reports one printed line. New
names are imported inside the tests, so a checkout without them fails each
test on its own. ``test_isolation_linux.py`` runs the same on a real zygote.
"""

import json
import os
import textwrap

import pytest


class _Zygote:
    """The zygote's half of an isolated run: keeps the request it is handed."""

    handed = []

    def __init__(self, socket_path):
        self.socket_path = socket_path

    def run(self, request, wall_timeout=None):
        _Zygote.handed.append(request)
        return 0, None, False


@pytest.fixture
def handed(tmp_path, monkeypatch):
    """A sandbox on a data folder of its own that runs Python isolated: the
    requests its zygote was handed, in order."""
    from utk_curio.sandbox.app import api
    from utk_curio.sandbox.isolation import runner, supervisor
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    (tmp_path / ".curio" / "data").mkdir(parents=True)
    config = runner.IsolationConfig.from_environment({
        "CURIO_EXEC_PARALLELISM": "1",
        "CURIO_EXEC_SOCKET": str(tmp_path / "exec-zygote.sock"),
        "CURIO_LAUNCH_CWD": str(tmp_path),
    })
    monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, config))
    monkeypatch.setattr(supervisor, "ZygoteClient", _Zygote)
    monkeypatch.setattr(
        supervisor, "read_child_manifest",
        lambda scratch_dir: {"ok": False, "stdout": ["the child ran"], "stderr": ""},
    )
    _Zygote.handed = []
    release_connection()
    init_db()
    yield _Zygote.handed
    release_connection()


def _libraries(key):
    """The folder of the node libraries of the account *key*."""
    from utk_curio.sandbox.isolation import supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    return supervisor.user_overlay_dir(str(_shared_data_dir()), key)


def _run(handed, user_key, **body):
    """``/exec`` of a run of the account *user_key*: the request the zygote
    was handed."""
    from utk_curio.sandbox.app import app

    resp = app.test_client().post("/exec", json={
        "code": textwrap.indent("return 1\n", "    "),
        "file_path": "",
        "nodeType": "ai.test.flood-tools/depth",
        "dataType": "",
        "session_id": "session-editor-libraries",
        "save_dataset": False,
        "user_key": user_key,
        **body,
    })
    reply = json.loads(resp.get_data(as_text=True))
    resp.close()
    assert reply["stdout"] == ["the child ran"], reply
    return handed[-1]


def test_an_editors_run_names_his_libraries_then_the_owners(handed):
    """bob ("8") runs a node of alice's ("7") dataflow: his folder first, so
    his own copy of a library wins, then hers. Hers is only located: the run
    writes nothing of hers."""
    request = _run(handed, "8", library_keys=["7"])

    assert request["overlay_dir"] == [_libraries("8"), _libraries("7")]
    assert os.path.isdir(_libraries("8"))
    assert not os.path.exists(_libraries("7"))


@pytest.mark.parametrize("user_key", ["7", "9"], ids=["the owner", "an account never invited"])
def test_any_other_run_names_its_own_libraries_alone(handed, user_key):
    """alice's own run of her dataflow, and the run of an account she never
    invited, which the backend sends no other key for, name their own folder,
    as before."""
    assert _run(handed, user_key)["overlay_dir"] == _libraries(user_key)


def test_only_plain_storage_keys_of_other_accounts_are_read(handed):
    """A key that would name another folder, one that is no text, the run's
    own key and a key named twice are left out; keys that are no list name
    no one."""
    request = _run(handed, "8", library_keys=["../7", "7/../../8", "", 7, None, "8", "7", "7"])
    assert request["overlay_dir"] == [_libraries("8"), _libraries("7")]

    assert _run(handed, "8", library_keys="7")["overlay_dir"] == _libraries("8")
