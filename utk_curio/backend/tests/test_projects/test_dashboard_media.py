"""A dashboard shows the images and videos its pinned tiles' rows name to
whoever opens its link, signed in or not, as it shows the rows themselves
(#1117). The media route needs a sign-in, and reads the caller's own
collections, so the page asks the dashboard for links to the files a tile's
output names (``POST /api/projects/<id>/dashboard/media``): signed links
(``media.sign``) to those files alone, read as the dataflow's owner reads
them. No other file of the owner's is reachable through it.

The dashboard here pins a Simple View fed by Photos, whose saved output holds
rows of the committed street survey as ``curio_load_collection`` gives them,
and saves the output of Aside, which no tile reads. The route is asked inside
each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.projects import services

#: The committed street survey: three photos and a video, in a folder of the repo.
SURVEY = "data.curio.storage-survey"
LINKS_ROUTE = "/api/projects/{pid}/dashboard/media"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _spec():
    """Photos feeding a pinned Simple View, and Aside, which no tile reads,
    as a dataflow saved from the canvas holds them (``TrillGenerator``)."""
    return {"dataflow": {
        "name": "Survey",
        "nodes": [
            {"id": "photos", "type": "curio.builtin/python-computation", "x": 0, "y": 0},
            {"id": "view", "type": "curio.builtin/vis-simple", "x": 300, "y": 0, "dashboardPinned": True},
            {"id": "aside", "type": "curio.builtin/python-computation", "x": 0, "y": 300},
        ],
        "edges": [{"id": "photos-view", "source": "photos", "target": "view"}],
    }}


def _frame(rows):
    """*rows* as ``/get`` sends a table: one list per column."""
    columns = list(rows[0])
    return {"dataType": "dataframe", "data": {column: [row[column] for row in rows] for column in columns}}


def _file(row):
    """What the page asks a link for: one file, as a row's URL names it."""
    return {"datasetId": row["dataset_id"], "fileId": row["file_id"], "kept": None}


@pytest.fixture()
def survey(monkeypatch, client, user_and_token):
    """The committed street survey in the owner's Data Catalog, its source
    read where the repo holds it: a row per file, as ``curio_load_collection``
    gives them, the photos first."""
    import pandas as pd

    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage
    from utk_curio.sandbox.util.collections import media_urls

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(Path(__file__).resolve().parents[4] / "discovery"))
    _, token = user_and_token
    item = client.get(f"/api/datasets/{SURVEY}", headers=_auth(token))
    assert item.status_code == 200, item.get_data(as_text=True)
    index = pd.read_parquet(item.get_json()["path"]).sort_values("kind", key=lambda kind: kind != "image")
    return [
        {"name": name, "dataset_id": SURVEY, "file_id": file_id, "kind": kind, **media_urls(SURVEY, file_id, kind)}
        for name, file_id, kind in zip(index["name"], index["file_id"], index["kind"])
    ]


@pytest.fixture()
def dashboard(client, user_and_token, survey, monkeypatch):
    """The dashboard: Photos saved with the first photo's row and the video's,
    which the pinned Simple View shows, and Aside with the second photo's."""
    _, token = user_and_token
    resp = client.post("/api/projects", data=json.dumps({"name": "Survey", "spec": _spec(), "outputs": []}),
                       headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    pid = resp.get_json()["id"]
    video = next(row for row in survey if row["kind"] == "video")
    envelopes = {"photos.parquet": _frame([survey[0], video]), "aside.parquet": _frame([survey[1]])}
    monkeypatch.setattr(services, "_dashboard_envelope_reader",
                        lambda _saved_path_of: lambda filename: envelopes[filename])
    loaded = services.load_shared_project

    def load(project_id, **kwargs):
        if project_id != pid:
            return loaded(project_id, **kwargs)
        return {
            "project": type("D", (), {"name": "Survey"})(),
            "spec": _spec(),
            "outputs": [
                {"node_id": "photos", "filename": "photos.parquet", "data_type": "dataframe"},
                {"node_id": "aside", "filename": "aside.parquet", "data_type": "dataframe"},
            ],
        }

    monkeypatch.setattr(services, "load_shared_project", load)
    return {"pid": pid, "shown": survey[0], "video": video, "aside": survey[1]}


def _links(client, pid, file_name, files, headers=None):
    return client.post(
        LINKS_ROUTE.format(pid=pid), data=json.dumps({"fileName": file_name, "files": files}),
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def test_a_viewer_with_no_account_sees_the_photo_a_pinned_simple_view_shows(client, dashboard):
    """The page asks with no sign-in, as a viewer's does: the photo its tile
    shows comes back as a link, whose thumbnail and file read with none."""
    shown = dashboard["shown"]

    res = _links(client, dashboard["pid"], "photos.parquet", [_file(shown)])

    assert res.status_code == 200, res.get_data(as_text=True)
    links = res.get_json()["links"]
    assert [(link["datasetId"], link["fileId"]) for link in links] == [(SURVEY, shown["file_id"])]
    assert res.get_json()["expiresIn"] == 600
    thumb = client.get(f"{links[0]['url']}?variant=thumb")
    assert (thumb.status_code, thumb.mimetype) == (200, "image/jpeg"), thumb.get_data(as_text=True)[:200]
    photo = client.get(f"{links[0]['url']}?variant=original")
    assert (photo.status_code, photo.mimetype) == (200, "image/jpeg"), photo.get_data(as_text=True)[:200]


def test_no_other_file_of_the_owners_is_reached(client, dashboard):
    """A file the tile's rows do not name gets no link, an output no tile
    reads gets none at all, and the media route itself still asks for a
    sign-in."""
    pid, aside = dashboard["pid"], dashboard["aside"]

    offered = _links(client, pid, "photos.parquet", [_file(aside), {**_file(aside), "kept": "k" + "0" * 32}])
    untiled = _links(client, pid, "aside.parquet", [_file(aside)])
    unknown = _links(client, pid, "someone-elses-artifact", [_file(aside)])

    assert offered.status_code == 200, offered.get_data(as_text=True)
    assert offered.get_json()["links"] == []
    assert (untiled.status_code, unknown.status_code) == (404, 404)
    assert client.get(aside["thumbnail"]).status_code == 401


def test_a_video_the_tile_shows_plays_from_its_link_with_range(client, dashboard):
    video = dashboard["video"]

    res = _links(client, dashboard["pid"], "photos.parquet", [_file(video)])

    assert res.status_code == 200, res.get_data(as_text=True)
    [link] = res.get_json()["links"]
    poster = client.get(f"{link['url']}?variant=poster")
    assert (poster.status_code, poster.mimetype) == (200, "image/jpeg")
    part = client.get(f"{link['url']}?variant=original", headers={"Range": "bytes=0-99"})
    assert (part.status_code, part.mimetype, len(part.data)) == (206, "video/mp4", 100)


def test_the_owner_signed_in_gets_the_same_photo(client, user_and_token, dashboard):
    _, token = user_and_token
    shown = dashboard["shown"]

    res = _links(client, dashboard["pid"], "photos.parquet", [_file(shown)], headers=_auth(token))

    assert res.status_code == 200, res.get_data(as_text=True)
    [link] = res.get_json()["links"]
    through_the_link = client.get(f"{link['url']}?variant=original")
    as_before = client.get(shown["image_url"], headers=_auth(token))
    assert (through_the_link.status_code, as_before.status_code) == (200, 200)
    assert through_the_link.data == as_before.data


def test_another_dashboards_page_reaches_none_of_them(client, user_and_token, dashboard):
    """The links name a dashboard's own tiles: another dataflow's page, here
    one with no pinned tile, gets none of this one's files."""
    _, token = user_and_token
    other = client.post("/api/projects", data=json.dumps({
        "name": "Other", "spec": {"dataflow": {"name": "Other", "nodes": [], "edges": []}}, "outputs": [],
    }), headers=_auth(token)).get_json()["id"]

    res = _links(client, other, "photos.parquet", [_file(dashboard["shown"])])

    assert res.status_code == 404
