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
- a saved output keeps its files when its node runs again, past its kept
  output's days and the sweep, and loses them when its Data Catalog dataset
  is deleted; so does the output a dataflow's first save records from a play
  of the canvas before that save;
- a play's files go with its kept output, and an invited editor's from his
  own media folder, with his kept output and with the dataflow;
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
    table the store holds, made in the run's session. Each row, in order."""
    import pandas as pd

    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import kept
    from utk_curio.sandbox.util.collections import make_collection_helpers
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    state = SimpleNamespace(rows=[], made={})

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
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


def _days_later(days: int) -> tuple:
    """``(prune's now, the sweep's now)`` *days* from now."""
    from utk_curio.backend.app.runs.models import naive_utc_now

    return naive_utc_now() + timedelta(days=days), time.time() + days * 24 * 3600


def _drawn_dataflow(client, sandbox, token, name="Overlays"):
    """A dataflow made by its first save, of Draw's output from a play of the
    canvas before it was saved, as the canvas saves one: its id, and that
    play's row."""
    first = _play(client, sandbox, token, None, "red")
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": [{"id": "draw", "type": CODE}], "edges": []}},
        "outputs": [{"node_id": "draw", "filename": first.artifact, "data_type": "dataframe"}],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert [output["node_id"] for output in body["outputs"]] == ["draw"], body
    return body["id"], first.row


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
    project_id, saved = _drawn_dataflow(client, sandbox, token)
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


def _kept_of(url: str):
    return parse_qs(urlparse(url).query).get("kept", [None])[0]


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
    project_id, row = _drawn_dataflow(client, sandbox, people.tokens["bob"], name="Bob's overlays")
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
