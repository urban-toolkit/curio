"""A dataset's derived files come with each copy of it into another account.

A computed dataset's rows name files a node derived from a collection's files
in its run's own folder (``&kept=<name>``), and the collection they came from
by its id, which a collection added from the Discovery Catalog holds in one
account alone. The stand-in node here, Draw, draws an overlay of one photo in
the colour its code names and returns the row it derived, as
``test_derived_files_per_run`` does, made in its run's session.

- alice publishes Draw's saved output, made from a collection she added from
  the Discovery Catalog; bob adds it to a dataflow of his: his canvas reads
  the overlay and the collection's photo, and carol, who holds neither, reads
  neither;
- bob's copy goes on reading them after alice runs Draw again, unpublishes it
  and deletes her dataset, and one added after alice's own files went reads
  them too;
- the sweep keeps bob's copy's files while the copy records them, and once
  alice unpublishes, bob's delete of his copy takes them;
- publishing again leaves only the new output in the shared catalog;
- a node of bob's reading a row's ``path`` opens his copy of the file;
- the collection bob gets lists only the photos the published rows name;
- carol, invited to edit bob's dataflow, reads its files through it;
- Save a copy into another account points each row's ``path`` at the copy's
  file, and leaves the source account's dataset as it was;
- alice's Apply of bob's request for his own computed dataset shows her its
  overlay.

Names main lacks are imported inside the tests, so the module imports there
and each test fails on its own.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project

CODE = "curio.builtin/python-computation"
#: The committed street survey, which every account's Data Catalog holds.
SURVEY = "data.curio.storage-survey"
#: The Discovery Catalog's folder source of the repo, whose survey alice adds.
EXAMPLE = "source.curio.example-storage@1"
COLOURS = {"red": (200, 30, 30), "blue": (30, 30, 200)}
TOKENS = {"bob": "bob-token-for-published-files", "carol": "carol-token-for-published-files"}
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


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


@pytest.fixture()
def people(db, user_and_token, tmp_path, monkeypatch):
    """alice, bob and carol, and a shared Data Catalog of the test's own,
    which holds the committed street survey as the shipped one does."""
    import shutil

    catalog = tmp_path / "catalog"
    shutil.copytree(REPO / "datasets" / f"{SURVEY}@1", catalog / f"{SURVEY}@1")
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    alice, alice_token = user_and_token
    return SimpleNamespace(
        alice=alice, bob=_account(db, "bob"), carol=_account(db, "carol"),
        tokens={"alice": alice_token, **TOKENS}, catalog=catalog,
    )


@pytest.fixture()
def draw(monkeypatch, client, people):
    """The sandbox as Draw's runs meet it: a run draws the photo *source*
    names, ``(collection id, file id)``, the committed street survey's first
    photo unless a test names another, in the colour its code names, where
    ``curio_derived_file`` says in the media folder the backend sent, and
    answers the row it derived as a table the store holds, made in the run's
    session. Each row, in order."""
    import pandas as pd

    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import kept
    from utk_curio.sandbox.util.collections import make_collection_helpers
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(REPO / "discovery"))
    item = client.get(f"/api/datasets/{SURVEY}", headers=auth_headers(people.tokens["alice"]))
    assert item.status_code == 200, item.get_data(as_text=True)
    index = pd.read_parquet(item.get_json()["path"])
    state = SimpleNamespace(source=(SURVEY, index[index["kind"] == "image"]["file_id"].tolist()[0]), rows=[], made={})

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        colour = body["code"].split("# colour ", 1)[1].split("\n", 1)[0].strip()
        derive = make_collection_helpers(None, {}, body.get("media_dir"))["curio_derived_file"]
        row = derive(*state.source, 0, "png", kind="image")
        Path(row["path"]).write_bytes(_png(COLOURS[colour]))
        state.rows.append(row)
        made = save_to_duckdb(pd.DataFrame([{"colour": colour, **row}]), node_id="draw", session_id=body["session_id"])
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


def _photos(client, token) -> tuple:
    """The Example storage source's survey, added from the Discovery Catalog:
    a collection under an id of this account's alone. Its id, its first
    photo's id, and its index."""
    from utk_curio.backend.tests.test_discovery.test_storage_media import collection

    dataset, index = collection(client, auth_headers(token), "survey", source=EXAMPLE)
    return dataset["id"], index[index["kind"] == "image"]["file_id"].iloc[0], index


def _draw(client, draw, token, project_id, colour) -> dict:
    """A Play of Draw in *colour* on the dataflow *project_id*, its output
    saved as the canvas saves it by default: the row it derived."""
    body = {
        "code": f"    # node draw\n    # colour {colour}\n    return input_0\n",
        "nodeType": CODE, "nodeId": "draw", "dataflowId": project_id,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": True,
    }
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["output"].get("path"), resp.get_json()
    return draw.rows[-1]


def _first_save(client, draw, token, name: str) -> tuple:
    """A dataflow made by its first save, of Draw's red output from a play of
    the canvas before it was saved, as the canvas saves one: its id and the
    row the play derived."""
    body = {
        "code": "    # node draw\n    # colour red\n    return input_0\n",
        "nodeType": CODE, "nodeId": "draw", "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    artifact = resp.get_json()["output"]["path"]
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": [{"id": "draw", "type": CODE}], "edges": []}},
        "outputs": [{"node_id": "draw", "filename": artifact, "data_type": "dataframe"}],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"], draw.rows[-1]


def _computed(project_id: str) -> str:
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    return computed_dataset_id("draw", project_id)


def _publish(client, token, project_id) -> str:
    """Publish Draw's saved output of *project_id*; the shared catalog's id."""
    resp = client.post("/api/datasets/publish", data=json.dumps(
        {"datasetId": _computed(project_id), "dataflowId": project_id},
    ), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _add(client, token, project_id, dataset_id) -> dict:
    """Add the shared catalog's *dataset_id* to the dataflow *project_id*."""
    resp = client.post(f"/api/dataflows/{project_id}/datasets/install",
                       data=json.dumps({"datasetId": dataset_id}), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _read(client, token, url):
    return client.get(url, headers={"Authorization": f"Bearer {token}"})


def _reads(client, token, url, colour) -> bool:
    read = _read(client, token, url)
    return (read.status_code, read.data == _png(COLOURS[colour])) == (200, True)


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _rows(data_path) -> list:
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    return read_dataset(str(data_path), "parquet").to_dict("records")


def _published_by_alice(client, people, draw) -> SimpleNamespace:
    """alice's dataflow of Draw on the survey she added from the Discovery
    Catalog, its red overlay saved and published: the collection's id, the
    photo's, the row, the dataflow's id and the published id."""
    collection_id, photo, index = _photos(client, people.tokens["alice"])
    draw.source = (collection_id, photo)
    project_id = create_project(client, people.tokens["alice"], name="Street overlays")
    row = _draw(client, draw, people.tokens["alice"], project_id, "red")
    assert row["dataset_id"] == collection_id, row
    return SimpleNamespace(collection=collection_id, photo=photo, index=index, row=row, project=project_id,
                           published=_publish(client, people.tokens["alice"], project_id))


def _added_by_bob(client, people, published: str) -> dict:
    """bob adds the published dataset to a dataflow of his: the copy, and
    the dataflow's id as ``project``."""
    project_id = create_project(client, people.tokens["bob"], name="Bob's street")
    return {**_add(client, people.tokens["bob"], project_id, published), "project": project_id}


# -- An account that adds a published dataset reads what its rows name ----------

def test_an_account_that_adds_a_published_dataset_reads_its_frames_and_its_collections_files(
    client, people, draw,
):
    """bob adds alice's published overlay. His canvas reads the overlay her
    node drew, and the photo of her collection it was drawn from, which his
    own Data Catalog never held. carol, who added nothing, reads neither."""
    alice = _published_by_alice(client, people, draw)
    _added_by_bob(client, people, alice.published)
    photo = f"/api/datasets/{alice.collection}/media/{alice.photo}?variant=thumb"

    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), (
        f"bob's copy reads no overlay: {_read(client, people.tokens['bob'], alice.row['image_url']).status_code}"
    )
    shown = _read(client, people.tokens["bob"], photo)
    assert shown.status_code == 200, f"bob's copy reads no photo of alice's collection: {shown.status_code}"
    assert _read(client, people.tokens["carol"], alice.row["image_url"]).status_code == 404
    assert _read(client, people.tokens["carol"], photo).status_code == 404


def test_the_copy_reads_its_files_after_the_publisher_runs_again_unpublishes_and_deletes(client, people, draw):
    """bob's copy goes on reading alice's red overlay after she draws Draw
    blue, unpublishes her dataset and deletes it."""
    alice = _published_by_alice(client, people, draw)
    _added_by_bob(client, people, alice.published)
    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), "bob's copy reads no overlay"

    _draw(client, draw, people.tokens["alice"], alice.project, "blue")
    resp = client.delete(f"/api/datasets/publish/{alice.published}", headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    resp = client.delete(f"/api/datasets/{_computed(alice.project)}", headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), (
        "bob's copy lost its overlay with alice's run, unpublish and delete"
    )


def test_a_published_dataset_keeps_its_files_once_its_publishers_go(client, people, draw):
    """alice draws Draw blue after publishing her red overlay, and a week
    on her red file goes: no output of hers names it. bob adds the published
    dataset after that and reads the red overlay all the same: the published
    dataset holds its files for as long as it is published."""
    from datetime import timedelta

    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import naive_utc_now

    alice = _published_by_alice(client, people, draw)
    _draw(client, draw, people.tokens["alice"], alice.project, "blue")
    kept.prune(now=naive_utc_now() + timedelta(days=8))
    kept.sweep_kept_media(now=time.time() + 8 * 24 * 3600)
    assert not Path(alice.row["path"]).exists(), "alice's red overlay stayed a week after her dataset moved on"

    _added_by_bob(client, people, alice.published)
    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), (
        f"a later add reads no overlay: {_read(client, people.tokens['bob'], alice.row['image_url']).status_code}"
    )


def test_the_sweep_keeps_the_copys_files_while_the_copy_records_them(client, people, draw):
    """The sweep keeps bob's copy's files past a week, once no kept output
    names them, since his copy records them, and takes them once no dataset
    of his does."""
    import shutil
    from datetime import timedelta

    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import naive_utc_now

    alice = _published_by_alice(client, people, draw)
    copy = _added_by_bob(client, people, alice.published)
    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), "bob's copy reads no overlay"

    a_week_on = time.time() + 8 * 24 * 3600
    kept.prune(now=naive_utc_now() + timedelta(days=8))
    kept.sweep_kept_media(now=a_week_on)
    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), "the sweep took bob's copy's overlay"

    shutil.rmtree(Path(copy["path"]).parents[1])
    kept.sweep_kept_media(now=a_week_on)
    assert _read(client, people.tokens["bob"], alice.row["image_url"]).status_code == 404, (
        "bob's overlay outlived the copy that named it"
    )


def test_a_node_of_the_adding_account_reads_its_own_copy_of_each_file(client, people, draw):
    """A node of bob's reading the copy's rows opens each row's ``path``: it
    names bob's copy of the overlay, in his own media folder, not alice's."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    alice = _published_by_alice(client, people, draw)
    copy = _added_by_bob(client, people, alice.published)
    (row,) = _rows(copy["path"])

    path = Path(row["path"])
    assert path.is_relative_to(media_dirs.media_work_root(_key(people.bob))), (
        f"bob's copy's row names {path}, outside his media folder"
    )
    assert path.read_bytes() == _png(COLOURS["red"])


def test_the_collection_an_adding_account_gets_lists_only_the_photos_the_rows_name(client, people, draw):
    """bob gets alice's collection under its own id, so the rows' links name
    a collection he holds, with only the photo her published rows name: not
    the rest of what she added from the Discovery Catalog."""
    import pandas as pd

    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    alice = _published_by_alice(client, people, draw)
    assert len(alice.index) > 1, "the survey holds one file: nothing is left out"
    _added_by_bob(client, people, alice.published)

    folder = dataset_dir(_key(people.bob), f"{alice.collection}@1")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8")) if folder.is_dir() else {}
    assert manifest.get("format") == "collection", f"bob holds no collection {alice.collection}"
    index = pd.read_parquet(folder / manifest["dataFile"])
    assert index["file_id"].tolist() == [alice.photo]


def test_the_copys_delete_takes_its_files_once_the_publisher_unpublishes(client, people, draw):
    """While alice's dataset is published, bob's copy is a copy of the shared
    catalog's, which the Data Catalog never offers to delete. Once she
    unpublishes it, bob's delete takes his copy, and its files go once no
    kept output names them."""
    from datetime import timedelta

    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import naive_utc_now

    alice = _published_by_alice(client, people, draw)
    copy = _added_by_bob(client, people, alice.published)
    assert _reads(client, people.tokens["bob"], alice.row["image_url"], "red"), "bob's copy reads no overlay"
    resp = client.delete(f"/api/datasets/publish/{alice.published}", headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    resp = client.delete(f"/api/datasets/{copy['id']}", headers=auth_headers(people.tokens["bob"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    kept.prune(now=naive_utc_now() + timedelta(days=8))
    kept.sweep_kept_media(now=time.time() + 8 * 24 * 3600)
    assert _read(client, people.tokens["bob"], alice.row["image_url"]).status_code == 404, (
        "bob's overlay outlived his deleted copy"
    )


def test_publishing_again_leaves_only_the_new_output_in_the_shared_catalog(client, people, draw):
    """alice publishes her red overlay, draws Draw blue and publishes again:
    the shared catalog holds the blue output alone, not the red one's file
    and records beside it, and bob, adding it after, reads the blue overlay."""
    alice = _published_by_alice(client, people, draw)
    blue = _draw(client, draw, people.tokens["alice"], alice.project, "blue")
    assert _publish(client, people.tokens["alice"], alice.project) == alice.published

    entry = people.catalog / f"{alice.published}@1"
    data_file = Path(json.loads((entry / "manifest.json").read_text(encoding="utf-8"))["dataFile"]).name
    left = sorted(path.name for path in (entry / "data").iterdir() if not path.name.startswith(data_file))
    assert left == [], f"publishing again left the earlier output's files in the shared catalog: {left}"
    _added_by_bob(client, people, alice.published)
    assert _reads(client, people.tokens["bob"], blue["image_url"], "blue"), "bob's later copy reads no blue overlay"


def test_an_editor_of_the_adding_accounts_dataflow_reads_its_files_through_it(client, people, draw):
    """bob adds alice's published overlay to his dataflow and invites carol
    to edit it. Her canvas reads the overlay and the collection's photo
    through his dataflow, as his does."""
    from utk_curio.backend.app.projects import access

    alice = _published_by_alice(client, people, draw)
    copy = _added_by_bob(client, people, alice.published)
    access.add_editor(people.bob, copy["project"], "carol")
    through = f"&dataflowId={copy['project']}"
    photo = f"/api/datasets/{alice.collection}/media/{alice.photo}?variant=thumb{through}"

    assert _reads(client, people.tokens["carol"], f"{alice.row['image_url']}{through}", "red"), (
        "carol reads no overlay of bob's copy: "
        f"{_read(client, people.tokens['carol'], alice.row['image_url'] + through).status_code}"
    )
    shown = _read(client, people.tokens["carol"], photo)
    assert shown.status_code == 200, f"carol reads no photo of bob's copy's collection: {shown.status_code}"


# -- Every copy into another account ------------------------------------------

def test_save_a_copy_into_another_account_points_each_rows_path_at_the_copys_file(client, people, draw):
    """bob's dataflow saved Draw's red overlay. alice saves a copy of it into
    her account: the copy's row names her copy of the overlay, in her media
    folder, and bob's dataset is left as it was."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    project_id, _row = _first_save(client, draw, people.tokens["bob"], "Bob's overlays")
    bobs = dataset_dir(_key(people.bob), f"{_computed(project_id)}@1")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in bobs.rglob("*") if path.is_file()}

    shared = client.get(f"/api/projects/{project_id}/shared")
    assert shared.status_code == 200, shared.get_data(as_text=True)
    name = "Bob's overlays (copy)"
    resp = client.post("/api/projects", data=json.dumps({
        "name": name, "copy_of": project_id, "outputs": shared.get_json()["outputs"],
        "spec": {"dataflow": {"name": name, "nodes": [{"id": "draw", "type": CODE}], "edges": []}},
    }), headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    copy = dataset_dir(_key(people.alice), f"{_computed(resp.get_json()['id'])}@1")
    data = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))["dataFile"]

    (row,) = _rows(copy / data)
    path = Path(row["path"])
    assert path.is_relative_to(media_dirs.media_work_root(_key(people.alice))), (
        f"alice's copy's row names {path}, outside her media folder"
    )
    assert path.read_bytes() == _png(COLOURS["red"])
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in bobs.rglob("*") if path.is_file()}
    assert after == before, "alice's copy changed bob's dataset"


def test_the_owners_apply_of_an_editors_computed_dataset_shows_her_its_overlay(client, people, draw):
    """bob, invited to edit alice's dataflow, asks her to add his own Draw
    output, made on a dataflow of his. Her Apply copies it into her store,
    and her canvas reads its overlay."""
    from utk_curio.backend.app.projects import access

    bobs_project = create_project(client, people.tokens["bob"], name="Bob's overlays")
    row = _draw(client, draw, people.tokens["bob"], bobs_project, "red")
    hers = create_project(client, people.tokens["alice"], name="Street overlays")
    access.add_editor(people.alice, hers, "bob")

    asked = client.post(f"/api/dataflows/{hers}/datasets/requests", json={"datasetId": _computed(bobs_project)},
                        headers=auth_headers(people.tokens["bob"]))
    assert asked.status_code == 201, asked.get_data(as_text=True)
    request = asked.get_json()["request"]
    applied = client.post(f"/api/dataflows/{hers}/datasets/requests/{request['proposalId']}/apply",
                          headers=auth_headers(people.tokens["alice"]))
    assert applied.status_code == 200, applied.get_data(as_text=True)

    assert _reads(client, people.tokens["alice"], f"{row['image_url']}&dataflowId={hers}", "red"), (
        "alice's copy of bob's dataset reads no overlay: "
        f"{_read(client, people.tokens['alice'], row['image_url']).status_code}"
    )
