"""Every run derives into a folder of its own (dataflow audit step 6).

A node that derives a file from one of a collection's files (a frame, a clip,
an overlay) writes it where ``curio_derived_file`` says, in the media folder
the backend hands its run. The stand-in node here, Draw, draws an overlay of
the committed street survey's first photo in the colour its code names, with
no tag, as a node whose package hashes no setting into the names it gives,
and returns the row it derived as a table the store holds, made in its run's
session, so a play or a save installs it as a run's output is installed.

- two plays of Draw with other code keep a file each, and each row's URL
  reads its own;
- two plays of the same code keep one output, the last one's, with its
  files: the first play's output still reads for an hour, then the sweep
  takes its session and its folder, the folder only once no saved output
  records it; two plays of other code keep both outputs, each with its own
  folder;
- a saved output keeps its files when its node runs again, past its kept
  output's days and the sweep, and loses them when its Data Catalog dataset
  is deleted; so does the output a dataflow's first save records from a play
  of the canvas before that save;
- a play's files go with its kept output, and an invited editor's from his
  own media folder, with his kept output and with the dataflow;
- a kept output that hands on a saved output's rows keeps their files once
  the saved output goes, until it goes too;
- two folders' files of one id keep a thumbnail each;
- an invited editor reads the files the owner's saved output names through
  her dataflow, by the media route and by the player's signed link, and an
  account she never invited reads none of them;
- Save a copy into another account brings the files its saved outputs name.

Names main lacks are imported inside the tests, so the module imports there
and each test fails on its own.
"""
from __future__ import annotations

import io
import json
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project

CODE = "curio.builtin/python-computation"
#: The committed street survey: three photos and a video, in a folder of the repo.
SURVEY = "data.curio.storage-survey"
COLOURS = {"red": (200, 30, 30), "blue": (30, 30, 200)}
TOKENS = {"bob": "bob-token-for-derived-files", "carol": "carol-token-for-derived-files"}
REPO = Path(__file__).resolve().parents[4]


class _Reply:
    status_code = 200
    ok = True
    text = ""
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        yield json.dumps(self._payload).encode("utf-8")

    def close(self):
        pass


def _png(colour) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, "PNG")
    return buffer.getvalue()


def _tone(jpeg: bytes) -> str:
    """Whether a thumbnail is drawn from the red overlay or the blue one."""
    from PIL import Image

    with Image.open(io.BytesIO(jpeg)) as image:
        pixel = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
    return "red" if pixel[0] > pixel[2] else "blue"


@pytest.fixture()
def survey(monkeypatch, client, user_and_token):
    """The committed street survey, which every account's Data Catalog
    holds, its source read where the repo keeps it: its first photo's id."""
    import pandas as pd

    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(REPO / "discovery"))
    _, token = user_and_token
    item = client.get(f"/api/datasets/{SURVEY}", headers=auth_headers(token))
    assert item.status_code == 200, item.get_data(as_text=True)
    index = pd.read_parquet(item.get_json()["path"])
    return index[index["kind"] == "image"]["file_id"].tolist()[0]


@pytest.fixture()
def sandbox(monkeypatch, survey):
    """The sandbox as Draw's runs meet it: a run draws the survey's first
    photo in the colour its code names, where ``curio_derived_file`` says in
    the media folder the backend sent, and answers the row it derived as a
    table the store holds, made in the run's session. Each row, in order. A
    run of After (``# hand on``) draws nothing and answers the first row
    drawn, as a node that hands on the rows it reads (a filter, a join). The
    sessions the backend asks it to forget are noted (``forgotten``)."""
    import pandas as pd

    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import kept
    from utk_curio.sandbox.util.collections import make_collection_helpers
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    state = SimpleNamespace(rows=[], made={}, forgotten=[])

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        if "# hand on" in body["code"]:
            handed = save_to_duckdb(pd.DataFrame([{"colour": "handed on", **state.rows[0]}]),
                                    node_id="after", session_id=body["session_id"])
            state.made[body["session_id"]] = handed
            return _Reply({"stdout": [], "stderr": "", "output": {"path": handed, "dataType": "dataframe"}})
        colour = body["code"].split("# colour ", 1)[1].split("\n", 1)[0].strip()
        derive = make_collection_helpers(None, {}, body.get("media_dir"))["curio_derived_file"]
        row = derive(SURVEY, survey, 0, "png", kind="image")
        Path(row["path"]).write_bytes(_png(COLOURS[colour]))
        state.rows.append(row)
        table = pd.DataFrame([{"colour": colour, **row}])
        made = save_to_duckdb(table, node_id="draw", session_id=body["session_id"])
        state.made[body["session_id"]] = made
        return _Reply({"stdout": [], "stderr": "", "output": {"path": made, "dataType": "dataframe"}})

    def sessions(method, path, **kwargs):
        named = json.loads(kwargs["data"])["sessionIds"]
        if path.endswith("/describe"):
            return _Reply({"sessions": {s: {"bytes": 10, "ids": [state.made.get(s, "")]} for s in named}})
        state.forgotten.extend(named)
        return _Reply({"forgotten": len(named)})

    monkeypatch.setattr(node_exec, "sandbox_request", run)
    monkeypatch.setattr(kept, "sandbox_request", sessions)
    return state


def _play(client, sandbox, token, project_id, colour, *, save=False):
    """A Play of Draw in *colour*, as the canvas posts one, on the dataflow
    *project_id*, or on a canvas not saved yet with none: the row it derived
    and the artifact its output is."""
    body = {
        "code": f"    # node draw\n    # colour {colour}\n    return input_0\n",
        "nodeType": CODE, "nodeId": "draw",
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": save,
    }
    if project_id:
        body["dataflowId"] = project_id
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    output = resp.get_json()["output"]
    assert output.get("path"), resp.get_json()
    return SimpleNamespace(row=sandbox.rows[-1], artifact=output["path"])


def _read(client, token, url):
    return client.get(url, headers={"Authorization": f"Bearer {token}"})


def _reads(client, token, url, colour) -> bool:
    """Whether *url* answers the overlay drawn in *colour* to *token*."""
    read = _read(client, token, url)
    return (read.status_code, read.data == _png(COLOURS[colour])) == (200, True)


def _kept_of(url: str):
    return parse_qs(urlparse(url).query).get("kept", [None])[0]


def _run_folder(row) -> Path:
    """The run's folder that holds *row*'s file: the one its URL names."""
    name = _kept_of(row["image_url"])
    return next(folder for folder in Path(row["path"]).parents if folder.name == name)


def _days_later(days: int) -> tuple:
    """``(prune's now, the sweep's now)`` *days* from now."""
    from utk_curio.backend.app.runs.models import naive_utc_now

    return naive_utc_now() + timedelta(days=days), time.time() + days * 24 * 3600


def _an_hour_on():
    """prune's now an hour and a minute from now: past the hour a replaced
    output still serves the pages and runs that read it."""
    from utk_curio.backend.app.runs.models import naive_utc_now

    return naive_utc_now() + timedelta(hours=1, minutes=1)


def _drawn_dataflow(client, sandbox, token, name="Overlays"):
    """A dataflow made by its first save, of Draw's output from a play of the
    canvas before it was saved, as the canvas saves one: its id, and that
    play (its row and its output's artifact)."""
    first = _play(client, sandbox, token, None, "red")
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": [{"id": "draw", "type": CODE}], "edges": []}},
        "outputs": [{"node_id": "draw", "filename": first.artifact, "data_type": "dataframe"}],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert [output["node_id"] for output in body["outputs"]] == ["draw"], body
    return body["id"], first


def _delete_dataset(client, token, project_id):
    """Delete the node Draw's saved output from the Data Catalog."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    resp = client.delete(f"/api/datasets/{computed_dataset_id('draw', project_id)}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


@pytest.fixture()
def people(db, user_and_token):
    alice, alice_token = user_and_token
    return SimpleNamespace(
        alice=alice, bob=_account(db, "bob"), carol=_account(db, "carol"),
        tokens={"alice": alice_token, **TOKENS},
    )


def _alices(client, people) -> str:
    """alice's dataflow of Draw, with bob invited to edit it."""
    from utk_curio.backend.app.projects import access

    project_id = create_project(client, people.tokens["alice"], name="Street overlays")
    access.add_editor(people.alice, project_id, "bob")
    return project_id


# -- Two runs never share a file ------------------------------------------------

def test_two_plays_of_a_node_with_other_code_keep_a_file_each(client, user_and_token, sandbox):
    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")

    first = _play(client, sandbox, token, project_id, "red").row
    second = _play(client, sandbox, token, project_id, "blue").row

    assert Path(first["path"]).read_bytes() == _png(COLOURS["red"]), (
        f"the second play wrote over the first play's file: both at {second['path']}"
    )
    assert Path(second["path"]).read_bytes() == _png(COLOURS["blue"])
    assert first["image_url"] != second["image_url"], "both rows name one file"
    assert _reads(client, token, first["image_url"], "red"), _read(client, token, first["image_url"]).status_code
    assert _reads(client, token, second["image_url"], "blue"), _read(client, token, second["image_url"]).status_code


# -- How long a run's files live ----------------------------------------------------

def test_a_saved_output_keeps_its_files_when_its_node_runs_again_and_loses_them_with_its_dataset(
    client, user_and_token, sandbox,
):
    """A play saves Draw's red overlay. A later play with other code saves
    nothing. Past 7 days the kept outputs of both plays go, and the sweep
    runs: the saved output's file is as its play drew it, and reads. Its
    Data Catalog delete takes it."""
    from utk_curio.backend.app.runs import kept

    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    saved = _play(client, sandbox, token, project_id, "red", save=True).row
    _play(client, sandbox, token, project_id, "blue")

    assert Path(saved["path"]).read_bytes() == _png(COLOURS["red"]), "a later play wrote over a saved output's file"
    prune_at, sweep_at = _days_later(kept.KEPT_DAYS + 1)
    assert kept.prune(now=prune_at) == 2
    kept.sweep_kept_media(now=sweep_at)
    assert Path(saved["path"]).read_bytes() == _png(COLOURS["red"]), "a saved output's file went with its kept output"
    assert _reads(client, token, saved["image_url"], "red"), _read(client, token, saved["image_url"]).status_code

    _delete_dataset(client, token, project_id)
    assert not Path(saved["path"]).exists(), "a deleted saved output's file stayed"
    assert _read(client, token, saved["image_url"]).status_code == 404


def test_the_first_save_keeps_the_files_of_a_play_made_before_it(client, user_and_token, sandbox):
    """A play of a canvas not saved yet draws red, the canvas's first save
    records that output, and a play with other code follows. The saved
    output's file stays as drawn, past 7 days and the sweep too, though no
    kept output ever named it, and its Data Catalog delete takes it at once."""
    from utk_curio.backend.app.runs import kept

    _, token = user_and_token
    project_id, first = _drawn_dataflow(client, sandbox, token)
    saved = first.row
    _play(client, sandbox, token, project_id, "blue")

    assert Path(saved["path"]).read_bytes() == _png(COLOURS["red"]), "a later play wrote over a saved output's file"
    prune_at, sweep_at = _days_later(kept.KEPT_DAYS + 1)
    kept.prune(now=prune_at)
    kept.sweep_kept_media(now=sweep_at)
    assert Path(saved["path"]).read_bytes() == _png(COLOURS["red"]), "a saved output's file went with the sweep"
    assert _reads(client, token, saved["image_url"], "red"), _read(client, token, saved["image_url"]).status_code

    _delete_dataset(client, token, project_id)
    assert not Path(saved["path"]).exists(), "a deleted saved output's file stayed"
    assert _read(client, token, saved["image_url"]).status_code == 404


def test_a_plays_files_go_with_its_kept_output(client, user_and_token, sandbox):
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput

    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    row = _play(client, sandbox, token, project_id, "red").row
    made_at = KeptStepOutput.query.filter_by(project_id=project_id).one().created_at

    assert kept.prune(now=made_at + timedelta(days=kept.KEPT_DAYS + 1)) == 1

    assert not Path(row["path"]).exists(), "the play's overlay outlived its kept output"
    assert _read(client, token, row["image_url"]).status_code == 404


def test_an_editors_files_go_from_his_media_folder_with_his_kept_output(client, people, sandbox):
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput

    project_id = _alices(client, people)
    row = _play(client, sandbox, people.tokens["bob"], project_id, "red").row
    entry = KeptStepOutput.query.filter_by(project_id=project_id).one()
    assert entry.made_by == kept.MADE_BY_EDITOR, entry.made_by
    drawn = Path(row["path"])
    assert drawn.is_relative_to(media_dirs.media_work_root(str(people.bob.id))), drawn

    assert kept.prune(now=entry.created_at + timedelta(days=kept.KEPT_DAYS + 1)) == 1

    assert not drawn.exists(), "bob's overlay outlived his kept output"


def test_an_editors_files_go_from_his_media_folder_with_the_dataflow(client, people, sandbox):
    project_id = _alices(client, people)
    drawn = Path(_play(client, sandbox, people.tokens["bob"], project_id, "red").row["path"])
    assert drawn.is_file()

    resp = client.delete(f"/api/projects/{project_id}", headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code in (200, 204), resp.get_data(as_text=True)

    assert not drawn.exists(), "bob's overlay outlived the dataflow"


def _hand_on(client, token, project_id, artifact):
    """A Play of After on the dataflow *project_id*, which hands on the rows
    of its input, *artifact*, as the canvas posts it."""
    resp = client.post("/processPythonCode", data=json.dumps({
        "code": "    # node after\n    # hand on\n    return input_0\n",
        "nodeType": CODE, "nodeId": "after", "dataflowId": project_id,
        "input": {"path": artifact, "dataType": "dataframe"}, "saveOutputDataset": False,
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["output"].get("path"), resp.get_json()


def test_a_kept_output_that_hands_on_a_saved_outputs_rows_keeps_their_files(client, user_and_token, sandbox):
    """The first save records Draw's red overlay, from a play of the canvas
    before it, which kept no output. A play of After hands that saved
    output's rows on and keeps its output, which names the folder they name:
    the overlay stays when the saved output is deleted from the Data Catalog,
    and goes with After's kept output."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput

    _, token = user_and_token
    project_id, first = _drawn_dataflow(client, sandbox, token)
    _hand_on(client, token, project_id, first.artifact)
    after = KeptStepOutput.query.filter_by(project_id=project_id, node_id="after").one()

    _delete_dataset(client, token, project_id)
    assert Path(first.row["path"]).read_bytes() == _png(COLOURS["red"]), (
        "deleting the saved output took the files a kept output that handed its rows on names"
    )
    assert _reads(client, token, first.row["image_url"], "red"), _read(client, token, first.row["image_url"]).status_code

    assert kept.prune(now=after.created_at + timedelta(days=kept.KEPT_DAYS + 1)) == 1
    assert not Path(first.row["path"]).exists(), "the overlay outlived the last output that named it"


# -- Identical runs share their files ------------------------------------------------

def test_a_play_of_the_same_code_replaces_the_last_ones_kept_output_and_files(client, user_and_token, sandbox):
    """Draw plays red twice on a saved dataflow: the same code on the same
    input, so the same key. The second play's kept output replaces the
    first's, which the sweep an hour on takes: one is left for the node, the
    sandbox forgets the first play's session, its run's folder goes and its
    row reads nothing, and the second play's row reads its own overlay. A
    node played again with nothing changed keeps one copy of its files."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput

    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    first = _play(client, sandbox, token, project_id, "red").row
    first_session = KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").one().session_id
    second = _play(client, sandbox, token, project_id, "red").row
    kept.prune(now=_an_hour_on())

    entries = KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").all()
    assert len(entries) == 1, f"two plays of the same code kept {len(entries)} outputs, not one"
    assert media_dirs.kept_media_name(entries[0].session_id) == _kept_of(second["image_url"]), (
        "the output left is not the last play's"
    )
    assert first_session in sandbox.forgotten, "the sandbox kept the replaced output's session"
    assert not _run_folder(first).exists(), "the replaced output's run folder stayed"
    assert _read(client, token, first["image_url"]).status_code == 404
    assert _reads(client, token, second["image_url"], "red"), _read(client, token, second["image_url"]).status_code


def test_a_replaced_output_reads_until_the_sweep_an_hour_on_takes_it(client, user_and_token, sandbox):
    """Draw plays red twice on a saved dataflow. The second play's request
    replaces the first play's kept output, but forgets no session and
    removes no folder: right after it, the first play's output still reads
    under its session and its overlay through its row's URL, while a reuse
    and a reopen pick the second's, and a sweep within the hour keeps it. The
    sweep an hour on takes its row, its session and its folder."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now

    user, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    first = _play(client, sandbox, token, project_id, "red").row
    made = KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").one()
    first_session, first_name, key = made.session_id, made.output_path, made.step_key
    second = _play(client, sandbox, token, project_id, "red").row
    later = KeptStepOutput.query.filter(
        KeptStepOutput.project_id == project_id, KeptStepOutput.session_id != first_session,
    ).one()

    assert sandbox.forgotten == [], f"the second play's request had the sandbox forget {sandbox.forgotten}"
    assert Path(first["path"]).is_file(), "the second play's request removed the first play's overlay"
    assert kept.owner_session(user.id, first_name) == first_session, "the replaced output no longer reads"
    assert _reads(client, token, first["image_url"], "red"), _read(client, token, first["image_url"]).status_code
    assert kept.kept_output(project_id, key)[1] == json.loads(later.artifact_ids), "a reuse picked the replaced output"
    assert kept.owner_outputs_by_key(project_id)[key].session_id == later.session_id, (
        "a reopen picked the replaced output"
    )
    assert kept.prune(now=naive_utc_now() + timedelta(minutes=59)) == 0, "a sweep within the hour took it"

    assert kept.prune(now=_an_hour_on()) == 1, "the sweep an hour on kept the replaced output"
    assert KeptStepOutput.query.filter_by(session_id=first_session).count() == 0
    assert first_session in sandbox.forgotten, "the sweep kept the replaced output's session"
    assert not _run_folder(first).exists(), "the sweep kept the replaced output's folder"
    assert _read(client, token, first["image_url"]).status_code == 404
    assert _reads(client, token, second["image_url"], "red"), _read(client, token, second["image_url"]).status_code


def test_a_replaced_outputs_files_stay_while_a_saved_output_records_them(client, user_and_token, sandbox):
    """Draw's red play is saved; a second play of the same code saves
    nothing. The first play's kept output is replaced, and the sweep an hour
    on takes it, but its run's folder stays, held by the saved output's
    record: the saved row and the new one each read their overlay. Deleting
    the saved output takes its folder, and, as deleting a node's saved output
    drops every output kept for the node (``kept.forget_node``), the second
    play's kept output and its folder too."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput

    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    saved = _play(client, sandbox, token, project_id, "red", save=True).row
    second = _play(client, sandbox, token, project_id, "red").row
    kept.prune(now=_an_hour_on())

    entries = KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").all()
    assert len(entries) == 1, f"two plays of the same code kept {len(entries)} outputs, not one"
    assert Path(saved["path"]).read_bytes() == _png(COLOURS["red"]), (
        "the saved output's file went with the kept output it replaced"
    )
    assert _reads(client, token, saved["image_url"], "red"), _read(client, token, saved["image_url"]).status_code
    assert _reads(client, token, second["image_url"], "red"), _read(client, token, second["image_url"]).status_code

    _delete_dataset(client, token, project_id)
    assert not _run_folder(saved).exists(), "a deleted saved output's run folder stayed"
    assert KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").count() == 0, (
        "deleting the node's saved output left an output kept for the node"
    )
    assert not _run_folder(second).exists(), "the node's kept output's run folder outlived its saved output's delete"
    assert _read(client, token, second["image_url"]).status_code == 404


def test_two_plays_of_other_code_keep_both_outputs_each_with_its_folder(client, user_and_token, sandbox):
    """Draw plays red, then blue: other code, so another key, and nothing is
    replaced. Both kept outputs stay, each naming the run's folder its row's
    URL names, which holds its own overlay."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.backend.app.runs.models import KeptStepOutput

    _, token = user_and_token
    project_id = create_project(client, token, name="Overlays")
    first = _play(client, sandbox, token, project_id, "red").row
    second = _play(client, sandbox, token, project_id, "blue").row

    entries = KeptStepOutput.query.filter_by(project_id=project_id, node_id="draw").all()
    assert len({entry.step_key for entry in entries}) == len(entries) == 2, [entry.step_key for entry in entries]
    assert {media_dirs.kept_media_name(entry.session_id) for entry in entries} == {
        _kept_of(first["image_url"]), _kept_of(second["image_url"]),
    }, "the kept outputs do not name the folders their rows name"
    assert not {entry.session_id for entry in entries} & set(sandbox.forgotten), sandbox.forgotten
    assert Path(first["path"]).read_bytes() == _png(COLOURS["red"]), "the second play wrote over the first play's file"
    assert Path(second["path"]).read_bytes() == _png(COLOURS["blue"])
    assert _reads(client, token, first["image_url"], "red"), _read(client, token, first["image_url"]).status_code
    assert _reads(client, token, second["image_url"], "blue"), _read(client, token, second["image_url"]).status_code


# -- Who reads them ----------------------------------------------------------------

def test_two_folders_files_of_one_id_keep_a_thumbnail_each(client, user_and_token, survey, monkeypatch):
    """Two runs' folders hold an overlay of one id each, red and blue. Each
    is read twice in turn: each thumbnail is drawn once, from its own file,
    and served from where it was cached after that."""
    from utk_curio.backend.app.discovery.application import media
    from utk_curio.backend.app.discovery.infrastructure import media_dirs
    from utk_curio.common.kept_sessions import new_session_id
    from utk_curio.sandbox.util.collections import make_collection_helpers

    user, token = user_and_token
    rows = {}
    for colour in COLOURS:
        folder = media_dirs.derived_root(str(user.id), kept=media_dirs.kept_media_name(new_session_id()))
        row = make_collection_helpers(None, {}, str(folder))["curio_derived_file"](
            SURVEY, survey, 0, "png", kind="image",
        )
        Path(row["path"]).write_bytes(_png(COLOURS[colour]))
        rows[colour] = row
    assert rows["red"]["file_id"] == rows["blue"]["file_id"]
    drawn = []
    draw = media._render
    monkeypatch.setattr(media, "_render", lambda found, variant, target: (
        drawn.append(str(found.local)), draw(found, variant, target))[1])

    for _ in range(2):
        for colour, row in rows.items():
            thumb = _read(client, token, row["thumbnail"])
            assert thumb.status_code == 200, thumb.get_data(as_text=True)[:300]
            assert _tone(thumb.data) == colour

    assert len(drawn) == 2, f"each folder's thumbnail was drawn again once the other's was: {drawn}"


def test_an_invited_editor_reads_the_files_the_owners_saved_output_names_through_her_dataflow(
    client, people, sandbox,
):
    """alice's play saves Draw's red overlay on her dataflow. bob, whom she
    invited, reads it through her dataflow, as his canvas asks for it: by the
    media route, and by the signed link the player asks for. carol, never
    invited, reads neither."""
    project_id = _alices(client, people)
    row = _play(client, sandbox, people.tokens["alice"], project_id, "red", save=True).row
    through = f"{row['image_url']}&dataflowId={project_id}"

    assert _reads(client, people.tokens["bob"], through, "red"), (
        "bob's canvas read no file of alice's saved output through her dataflow: "
        f"{_read(client, people.tokens['bob'], through).status_code}"
    )
    kept_folder = _kept_of(row["image_url"])
    query = {"dataflowId": project_id, **({"kept": kept_folder} if kept_folder else {})}
    link = client.post(f"/api/datasets/{SURVEY}/media/{row['file_id']}/link", query_string=query,
                       headers=auth_headers(people.tokens["bob"]))
    assert link.status_code == 200, link.get_data(as_text=True)
    played = client.get(f"{link.get_json()['url']}?variant=original")
    assert (played.status_code, played.data == _png(COLOURS["red"])) == (200, True), played.status_code

    assert _read(client, people.tokens["carol"], through).status_code == 404


def test_save_a_copy_into_another_account_brings_the_files_its_outputs_name(client, people, sandbox):
    """bob's dataflow saved Draw's red overlay. alice saves a copy of it into
    her account: the copy's row reads the overlay in her account, and goes on
    reading it once bob deletes his saved output."""
    project_id, first = _drawn_dataflow(client, sandbox, people.tokens["bob"], name="Bob's overlays")
    row = first.row
    shared = client.get(f"/api/projects/{project_id}/shared")
    assert shared.status_code == 200, shared.get_data(as_text=True)
    name = "Bob's overlays (copy)"
    resp = client.post("/api/projects", data=json.dumps({
        "name": name, "copy_of": project_id, "outputs": shared.get_json()["outputs"],
        "spec": {"dataflow": {"name": name, "nodes": [{"id": "draw", "type": CODE}], "edges": []}},
    }), headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert [output["node_id"] for output in resp.get_json()["outputs"]] == ["draw"], resp.get_json()

    assert _reads(client, people.tokens["alice"], row["image_url"], "red"), (
        f"alice's copy reads no file of its saved output: {_read(client, people.tokens['alice'], row['image_url']).status_code}"
    )
    _delete_dataset(client, people.tokens["bob"], project_id)
    assert _reads(client, people.tokens["alice"], row["image_url"], "red"), (
        "the copy's file went with bob's saved output"
    )
