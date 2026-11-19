"""What one hosted guest adds to the Data Catalog is theirs alone.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, whose dataset store every guest reads. A file a
hosted guest imports, and a dataset they download from the Discovery Catalog,
are kept in that store for them alone until the server starts again, as a
node's output they add to an example is (``projects/visitor_copies.py``).
These tests sign two visitors, A and B, in to that account, as
``test_guest_copy_leaks.py`` does:

- A imports a file and downloads a dataset from a storage source, a folder
  read from disk with no socket: A finds both everywhere, B nowhere, by
  listing or by id, and both go when the server starts;
- an agent's run for A reads A's upload and A's added output by id, on the
  server's request and on a job's own thread; one for B reads neither;
- Simple View's player plays a video of a collection A downloaded through a
  signed link, which a ``<video>`` asks for with no sign-in: as A, through
  whatever dataflow A's canvas shows, and that one file alone;
- a frame A's node derives from the video of a collection every guest reads,
  on a play or in an agent's job, is A's alone: B reads it neither by its id
  nor by a link, B's node deriving the same frame leaves A's as A's node
  wrote it, and it goes when the server starts;
- without ``--deploy`` the shared guest is the one local user, whose uploads
  and downloads are the account's, and so is what its nodes derive.
"""
from __future__ import annotations

import io
import json
import os
import time

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.tests.test_agents.test_run_node_datasets import (
    ATTACHMENT,
    COMPUTATION,
    _loader,
    _run_through_the_node_after,
)
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_discovery.conftest import (  # noqa: F401  (fixtures)
    _reset_discovery_process_state,
    discovery_dir,
    storage_folder,
    storage_source,
    workers_finish_first,
)
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401  (fixtures)
    VISITOR_A,
    VISITOR_B,
    _copy_of,
    _digests,
    _in_the_dataflow,
    _play,
    app,
    example,
    sandbox,
)
from utk_curio.backend.tests.test_projects.test_guest_store_leaks import _listing, _listings_of, _live

#: The storage source of ``storage_source``, and its row of one table.
SOURCE = "source.example.folder@1"
STATIONS = "stations"
#: The shipped storage source, whose survey row holds a video, and that video.
EXAMPLE_STORAGE = "source.curio.example-storage@1"
CLIP = "clip_01.mp4"


def _import(client, token: str) -> str:
    """The id of the file the visitor signed in as *token* imports, as the
    Data Catalog's Import does."""
    resp = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _added(client, token: str, source: str = SOURCE, row: str = STATIONS) -> dict:
    """The dataset the visitor signed in as *token* adds to the Data Catalog
    from *source*'s *row*, once its download's worker has ended
    (``workers_finish_first``)."""
    resp = client.post(f"/api/discovery/sources/{source}/resources/{row}/acquire",
                       headers=auth_headers(token), json={})
    assert resp.status_code in (200, 202), resp.get_data(as_text=True)
    body = resp.get_json()
    if "jobId" not in body:
        return body["dataset"]
    job = client.get(f"/api/discovery/jobs/{body['jobId']}", headers=auth_headers(token)).get_json()
    assert job["status"] == "completed", job
    return job["dataset"]


def _download(client, token: str) -> str:
    """The id of the dataset the visitor signed in as *token* adds to the Data
    Catalog from the storage source's stations row (:func:`_added`)."""
    return _added(client, token)["id"]


def _listed(client, token: str, query: dict) -> set[str]:
    return {item["id"] for item in _listing(client, token, **query)}


def test_a_hosted_guests_uploads_and_downloads_are_theirs_alone(client, example, storage_source, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    # Each visitor's Data Catalog lists the store once, as their canvases do,
    # before anything is measured.
    for token in (VISITOR_A, VISITOR_B):
        _listing(client, token, dataflowId=example)
    before = _digests(example)

    uploaded, downloaded = _import(client, VISITOR_A), _download(client, VISITOR_A)
    mine = {uploaded, downloaded}

    # A finds both in every listing and by id.
    for query in _listings_of(example):
        assert mine <= _listed(client, VISITOR_A, query), query
    for dataset_id in mine:
        shown = client.get(f"/api/datasets/{dataset_id}", headers=auth_headers(VISITOR_A))
        assert shown.status_code == 200, shown.get_data(as_text=True)
    # B finds neither: not listed, and not read, previewed, downloaded or added
    # to B's dataflow by id.
    for query in _listings_of(example):
        assert not mine & _listed(client, VISITOR_B, query), query
    for dataset_id in mine:
        for read in (f"/api/datasets/{dataset_id}", f"/api/datasets/{dataset_id}/preview",
                     f"/api/datasets/{dataset_id}/download"):
            resp = client.get(read, query_string={"dataflowId": example}, headers=auth_headers(VISITOR_B))
            assert resp.status_code == 404, (read, resp.status_code)
        added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": dataset_id}),
                            headers=auth_headers(VISITOR_B))
        assert added.status_code == 404, added.get_data(as_text=True)
    # B's download of the same row is B's own.
    theirs = _download(client, VISITOR_B)
    assert theirs not in mine
    assert theirs not in _listed(client, VISITOR_A, {})

    # A's upload added to the example goes in A's copy of it alone.
    added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": uploaded}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert uploaded in _in_the_dataflow(client, VISITOR_A, example)
    assert uploaded not in _in_the_dataflow(client, VISITOR_B, example)

    # They go when the server starts, and the store and the example are as
    # they were.
    visitor_copies.drop_all()
    for token in (VISITOR_A, VISITOR_B):
        assert not (mine | {theirs}) & _listed(client, token, {}), token
    assert _digests(example) == before


def _with_a_loader(example: str, *dataset_ids: str) -> None:
    """The example loads *dataset_ids*: a Data Loading node whose code names
    them, and a Python node after it with an agent's chat attached, as a chat
    that runs it has one. Written before any visitor's first change makes
    their copy of the example, so each copy starts from it."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    code = "".join(f'd{i} = curio_load_data("{d}")\n' for i, d in enumerate(dataset_ids)) + "return d0\n"
    with dataflow_docs.writing(GUEST_KEY, example, dataflow_docs.by_curio(GUEST_KEY, "test")) as spec:
        dataflow = spec["dataflow"]
        dataflow["nodes"] = [*dataflow["nodes"], _loader(code), {
            "id": "after", "type": COMPUTATION, "content": "return input_0\n",
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {},
        }]
        dataflow["edges"] = [*dataflow["edges"], {"id": "reactflow__edge-loadout-afterin",
                                                  "source": "load", "target": "after"}]
        dataflow["agentAttachments"] = [{
            "attachmentId": ATTACHMENT, "coord": "agent.curio.node-builder@1",
            "target": {"kind": "node", "targetId": "after"},
        }]


def _a_upload_and_an_added_output(client, example: str, sandbox) -> tuple[str, str]:
    """A's upload, and the output of the example's node a that A adds to the
    example as the Data Catalog lists it, each by id. The example loads both
    (:func:`_with_a_loader`)."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    uploaded = _import(client, VISITOR_A)
    output = computed_dataset_id("a", _copy_of(VISITOR_A, example))
    _with_a_loader(example, uploaded, output)
    made = sandbox["artifacts"]["a"]
    _play(client, VISITOR_A, example, "a")
    live = next(item for item in _listing(client, VISITOR_A, dataflowId=example, liveOutputs=_live("a", made))
                if item.get("producerNodeId") == "a")
    added = client.post(f"/api/dataflows/{example}/datasets/install",
                        data=json.dumps({"datasetId": live["id"], "sourceItem": live, "nodeTitle": "a"}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert added.get_json()["id"] == output
    return uploaded, output


def test_an_agents_run_for_a_hosted_guest_reads_their_own_datasets_alone(client, example, sandbox, monkeypatch):
    uploaded, output = _a_upload_and_an_added_output(client, example, sandbox)

    # The run through the node after the loader, from the agent's chat.
    done, sent = _run_through_the_node_after(client, VISITOR_A, example, monkeypatch)
    assert done["order"] == ["load", "after"], done
    assert set(sent[0].get("dataset_paths") or {}) == {uploaded, output}, sent[0]

    done, sent = _run_through_the_node_after(client, VISITOR_B, example, monkeypatch)
    assert done["order"] == ["load", "after"], done
    assert not sent[0].get("dataset_paths"), sent[0]


def test_an_agents_job_for_a_hosted_guest_reads_their_own_datasets_on_its_thread(app, client, example, sandbox):
    """A Solve's job runs on a thread of its own, which holds no request: the
    paths of a dataset its code names after it started are read there
    (``grounding._session_dataset_paths``), for the visitor whose request
    started it."""
    from utk_curio.backend.app.agents.application.turns import grounding
    from utk_curio.backend.app.agents.infrastructure import agent_jobs
    from utk_curio.backend.app.users.models import User

    uploaded, output = _a_upload_and_an_added_output(client, example, sandbox)
    code = f'a = curio_load_data("{uploaded}")\nb = curio_load_data("{output}")\nreturn a\n'
    read: dict = {}

    def _reading(token: str):
        guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
        read[token] = grounding._session_dataset_paths(_copy_of(token, example), guest, {}, [code])
        yield "done", {}

    for token in (VISITOR_A, VISITOR_B):
        with app.test_request_context(headers=auth_headers(token)):
            job = agent_jobs.start_job(
                user_key=GUEST_KEY, project_id=_copy_of(token, example), attachment_id=f"att-{token}",
                kind="solve-node", job_id=f"job-{token}", events=_reading(token),
            )
        job.thread.join(timeout=60)
        assert not job.thread.is_alive(), token

    assert set(read[VISITOR_A]) == {uploaded, output}, read
    assert read[VISITOR_B] == {}, read


# ---------------------------------------------------------------------------
# A collection's video, as Simple View's player plays it
# ---------------------------------------------------------------------------

@pytest.fixture()
def example_storage(monkeypatch):
    """The shipped storage source, listed afresh, as ``test_storage_media.py``
    reads it."""
    from utk_curio.backend.app.discovery.application import scan
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT

    monkeypatch.setenv(storage.ENV_ROOT, str(SHIPPED_ROOT))
    scan.listings.reset()
    yield EXAMPLE_STORAGE
    scan.listings.reset()


def _a_video(client, token: str, source: str) -> tuple[str, str, bytes]:
    """The collection the visitor signed in as *token* downloads from the
    survey row of *source*, the shipped storage source: its id, its video's
    file id, and the video's bytes, read from the source's folder."""
    import pandas as pd

    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.infrastructure.storage import storage_root
    from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT

    dataset = _added(client, token, source, "survey")
    row = pd.read_parquet(dataset["path"]).set_index("name").loc[CLIP]
    video = storage_root(load_source_manifest(SHIPPED_ROOT / source)) / row["relpath"]
    return dataset["id"], row["file_id"], video.read_bytes()


def _link(client, token: str, collection: str, file_id: str, *, dataflow: str | None = None) -> str:
    """The signed link Simple View's player asks for to play *file_id* of
    *collection*, as the visitor signed in as *token*, through the dataflow
    its canvas shows, *dataflow* (``?dataflowId=``)."""
    query = {"dataflowId": dataflow} if dataflow else {}
    resp = client.post(f"/api/datasets/{collection}/media/{file_id}/link", query_string=query,
                       headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["url"]


def test_a_hosted_guests_video_plays_from_its_link_with_no_sign_in(client, example, example_storage, monkeypatch):
    """Simple View's player asks for a link to A's video (``POST .../link``)
    and plays it in a ``<video>``, which sends no sign-in and asks by Range:
    the link answers with A's video, in part and whole."""
    workers_finish_first(monkeypatch)
    collection, clip, video = _a_video(client, VISITOR_A, example_storage)

    url = _link(client, VISITOR_A, collection, clip)
    part = client.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206, part.get_data(as_text=True)[:300]
    assert (part.mimetype, part.data) == ("video/mp4", video[10:20])
    whole = client.get(url)
    assert whole.status_code == 200, whole.get_data(as_text=True)[:300]
    assert whole.data == video


@pytest.mark.parametrize("through", ["example", "copy", "new"])
def test_a_hosted_guests_video_plays_from_a_link_minted_through_their_dataflow(
    client, example, example_storage, monkeypatch, through,
):
    """A's canvas asks for the link through the dataflow it shows
    (``?dataflowId=``), which the link names. A adds the collection to it
    first: to the example, which makes A's copy of it, or to the dataflow
    A's File > New made. The link is minted through the example, through A's
    copy by its id, as A's agents name it, or through A's new dataflow, and
    plays A's video with no sign-in."""
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.tests.test_projects.test_guest_new_dataflows import _new_dataflow

    workers_finish_first(monkeypatch)
    collection, clip, video = _a_video(client, VISITOR_A, example_storage)
    shown = _new_dataflow(client, VISITOR_A) if through == "new" else example
    added = client.post(f"/api/dataflows/{shown}/datasets/install", data=json.dumps({"datasetId": collection}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    dataflow = _copy_of(VISITOR_A, example) if through == "copy" else shown
    own = visitor_copies.is_own_copy(VISITOR_A, dataflow)
    assert own == (through != "example"), (through, dataflow, own)

    url = _link(client, VISITOR_A, collection, clip, dataflow=dataflow)
    part = client.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206, part.get_data(as_text=True)[:300]
    assert part.data == video[10:20]


def test_a_hosted_guests_link_names_no_sign_in_and_plays_their_video_alone(
    client, example, example_storage, monkeypatch,
):
    """A link is a bearer credential whose payload whoever holds it reads: it
    names the visitor as their datasets' ids do (``visitor_copies.visitor_of``),
    never by the sign-in. It plays the one file it names, as the visitor who
    asked for it, whatever sign-in its request sends: a link signed for A that
    names B's video finds nothing, B's own link plays B's, and A's video is
    read no other way, with no sign-in or as B."""
    from utk_curio.backend.app.discovery.application import media
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    collection, clip, video = _a_video(client, VISITOR_A, example_storage)
    theirs, their_clip = _a_video(client, VISITOR_B, example_storage)[:2]

    url = _link(client, VISITOR_A, collection, clip)
    for sent in ({}, auth_headers(VISITOR_B)):
        part = client.get(url, headers={**sent, "Range": "bytes=10-19"})
        assert part.status_code == 206, (sent, part.get_data(as_text=True)[:300])
        assert part.data == video[10:20], sent
    claims = media.verify(url.rsplit("/", 1)[1])
    payload = json.dumps(claims)
    assert VISITOR_A not in payload, payload
    assert (claims["d"], claims["f"]) == (collection, clip), payload

    forged = media.sign(claims["u"], claims["k"], theirs, their_clip, visitor=visitor_copies.visitor_of(VISITOR_A))
    refused = client.get(f"/api/media/{forged}", headers={"Range": "bytes=10-19"})
    assert refused.status_code == 404, refused.get_data(as_text=True)[:300]
    their_link = _link(client, VISITOR_B, theirs, their_clip)
    played = client.get(their_link, headers={"Range": "bytes=10-19"})
    assert played.status_code == 206, played.get_data(as_text=True)[:300]
    assert played.data == video[10:20]

    original = f"/api/datasets/{collection}/media/{clip}?variant=original"
    unsigned = client.get(original)
    assert unsigned.status_code == 401, unsigned.get_data(as_text=True)[:300]
    as_b = client.get(original, headers=auth_headers(VISITOR_B))
    assert as_b.status_code == 404, as_b.get_data(as_text=True)[:300]


def test_without_deploy_the_local_guests_uploads_and_downloads_are_the_accounts(
    client, example, storage_source, monkeypatch,
):
    """Without ``--deploy`` the shared guest is the one local user: whatever
    sign-in asks, it reads what the account holds, and a start keeps it."""
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)

    held = {_import(client, VISITOR_A), _download(client, VISITOR_A)}

    visitor_copies.drop_all()
    for token in (VISITOR_A, VISITOR_B):
        assert held <= _listed(client, token, {}), token


# ---------------------------------------------------------------------------
# What a node derives from a collection's files: frames, clips, overlays
# ---------------------------------------------------------------------------

#: The time of the frame each visitor's node derives from the video, in ms.
FRAME_MS = 500


def _a_video_every_guest_sees(client, monkeypatch, source: str) -> tuple[str, str, bytes]:
    """The collection of *source*'s survey row (:func:`_a_video`), added to
    the guest account with sign-in off, as the ``example`` fixture saves the
    example: no visitor added it, so every hosted guest reads it."""
    from utk_curio.backend.app.projects import visitor_copies

    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    try:
        collection, clip, video = _a_video(client, VISITOR_A, source)
    finally:
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    adder = visitor_copies.added_by(collection)
    assert adder is None, collection
    return collection, clip, video


def _a_frame(color: tuple[int, int, int]) -> bytes:
    """A JPEG frame of one *color*, as Sample Video Frames writes one."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "JPEG")
    return out.getvalue()


def _written(sent: dict, collection: str, clip: str, frame: bytes) -> dict:
    """The row of the frame of *collection*'s video *clip* at
    :data:`FRAME_MS` that node code handed *sent*, a run's collections and
    media folder, writes as *frame*, through the sandbox's own
    ``curio_derived_file``, as Sample Video Frames writes one."""
    from utk_curio.sandbox.util.collections import make_collection_helpers

    derive = make_collection_helpers(None, sent.get("collections"), sent.get("media_dir"))["curio_derived_file"]
    row = derive(collection, clip, FRAME_MS)
    with open(row["path"], "wb") as handle:
        handle.write(frame)
    return row


def _derives_in_a_play(client, sandbox, token: str, example: str, collection: str, clip: str,
                       frame: bytes) -> dict:
    """The visitor signed in as *token* plays the example's node a, whose
    code writes *frame* where its run's ``curio_derived_file`` says
    (:func:`_written`); the row it wrote."""
    _play(client, token, example, "a")
    return _written(sandbox["runs"]["a"], collection, clip, frame)


def _derives_in_a_job(app, token: str, example: str, collection: str, clip: str, frame: bytes) -> dict:
    """An agent's job for the visitor signed in as *token*, on a thread of
    its own, which holds no request: a Solve's attempt there is handed the
    collections its code reads and its media folder
    (``grounding._session_collections``), and the code writes *frame* there
    (:func:`_written`); the row it wrote."""
    from utk_curio.backend.app.agents.application.turns import grounding
    from utk_curio.backend.app.agents.infrastructure import agent_jobs
    from utk_curio.backend.app.users.models import User

    handed: dict = {}
    code = f'frames = curio_load_collection("{collection}")\nreturn frames\n'

    def _attempt():
        guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
        handed["collections"], handed["media_dir"] = grounding._session_collections(
            _copy_of(token, example), GUEST_KEY, guest, {}, [code],
        )
        yield "done", {}

    with app.test_request_context(headers=auth_headers(token)):
        job = agent_jobs.start_job(
            user_key=GUEST_KEY, project_id=_copy_of(token, example), attachment_id=f"att-{token}",
            kind="solve-node", job_id=f"job-{token}", events=_attempt(),
        )
    job.thread.join(timeout=60)
    running = job.thread.is_alive()
    assert not running, token
    return _written(handed, collection, clip, frame)


def _original(client, token: str, collection: str, file_id: str):
    """*file_id* of *collection*, the file itself, as the visitor signed in
    as *token* reads it."""
    return client.get(f"/api/datasets/{collection}/media/{file_id}", query_string={"variant": "original"},
                      headers=auth_headers(token))


@pytest.mark.parametrize("ran", ["play", "job"])
def test_a_frame_a_hosted_guests_node_derives_is_theirs_alone(
    app, client, example, example_storage, sandbox, monkeypatch, ran,
):
    """A's node derives a frame from the video of a collection every guest
    reads, on a play or in an agent's job. A reads it by its id. B reads the
    video, but not the frame, its thumbnail or a link to it, though its id is
    the video's and a time anyone can name. It goes when the server starts."""
    from utk_curio.backend.app.projects import visitor_copies

    workers_finish_first(monkeypatch)
    collection, clip, video = _a_video_every_guest_sees(client, monkeypatch, example_storage)
    frame = _a_frame((200, 30, 30))
    if ran == "play":
        row = _derives_in_a_play(client, sandbox, VISITOR_A, example, collection, clip, frame)
    else:
        row = _derives_in_a_job(app, VISITOR_A, example, collection, clip, frame)

    mine = _original(client, VISITOR_A, collection, row["file_id"])
    assert (mine.status_code, mine.data == frame) == (200, True), mine.status_code
    seen = _original(client, VISITOR_B, collection, clip)
    assert (seen.status_code, seen.data == video) == (200, True), seen.status_code
    for variant in ("original", "thumb"):
        theirs = client.get(f"/api/datasets/{collection}/media/{row['file_id']}",
                            query_string={"variant": variant}, headers=auth_headers(VISITOR_B))
        assert theirs.status_code == 404, (variant, theirs.status_code)
    link = client.post(f"/api/datasets/{collection}/media/{row['file_id']}/link",
                       headers=auth_headers(VISITOR_B))
    assert link.status_code == 404, link.get_data(as_text=True)

    visitor_copies.drop_all()
    gone = _original(client, VISITOR_A, collection, row["file_id"])
    assert gone.status_code == 404, gone.status_code


def _two_frames() -> tuple[bytes, bytes]:
    """A red frame and a blue one of one size: the shorter is padded after
    its end, which no decoder reads."""
    red, blue = _a_frame((200, 30, 30)), _a_frame((30, 30, 200))
    size = max(len(red), len(blue))
    return red.ljust(size, b"\0"), blue.ljust(size, b"\0")


def _tone(jpeg: bytes) -> str:
    """Whether a thumbnail is drawn from the red frame or the blue one."""
    from PIL import Image

    with Image.open(io.BytesIO(jpeg)) as image:
        pixel = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
    return "red" if pixel[0] > pixel[2] else "blue"


def test_a_hosted_guest_deriving_the_same_frame_leaves_anothers_as_their_node_wrote_it(
    client, example, example_storage, sandbox, monkeypatch,
):
    """A's node, then B's, derive the frame of one video every guest reads at
    one time, so one id names both. A's file is as A's node wrote it, and
    each visitor reads their own: the file, its thumbnail, and a link, which
    plays the frame of the visitor who asked for it with no sign-in or with
    another's. The two frames are of one size and time here, as two runs at
    once can make them, so only where each is tells their thumbnails apart."""
    workers_finish_first(monkeypatch)
    collection, clip = _a_video_every_guest_sees(client, monkeypatch, example_storage)[:2]
    red, blue = _two_frames()
    mine = _derives_in_a_play(client, sandbox, VISITOR_A, example, collection, clip, red)
    a_link = _link(client, VISITOR_A, collection, mine["file_id"])
    theirs = _derives_in_a_play(client, sandbox, VISITOR_B, example, collection, clip, blue)
    assert theirs["file_id"] == mine["file_id"], (mine, theirs)

    with open(mine["path"], "rb") as handle:
        kept = handle.read()
    assert kept == red, "B's node wrote over the frame A's node made"
    made = time.time_ns()
    for row in (mine, theirs):
        os.utime(row["path"], ns=(made, made))
    for token, frame, tone in ((VISITOR_A, red, "red"), (VISITOR_B, blue, "blue")):
        read = _original(client, token, collection, mine["file_id"])
        assert (read.status_code, read.data == frame) == (200, True), (token, read.status_code)
        thumb = client.get(f"/api/datasets/{collection}/media/{mine['file_id']}", headers=auth_headers(token))
        drawn = _tone(thumb.data) if thumb.status_code == 200 else thumb.status_code
        assert drawn == tone, (token, drawn)
    for sent in ({}, auth_headers(VISITOR_B)):
        played = client.get(a_link, headers=sent)
        assert (played.status_code, played.data == red) == (200, True), (sent, played.status_code)
    b_link = _link(client, VISITOR_B, collection, mine["file_id"])
    played = client.get(b_link)
    assert (played.status_code, played.data == blue) == (200, True), played.status_code


def test_without_deploy_what_the_local_guests_nodes_derive_is_the_accounts(
    client, example, example_storage, sandbox, monkeypatch,
):
    """Without ``--deploy`` the shared guest is the one local user: what its
    nodes derive is written in the account's media folder, as an account's
    is, whatever sign-in plays them, and read by any."""
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    workers_finish_first(monkeypatch)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    collection, clip = _a_video(client, VISITOR_A, example_storage)[:2]
    frame = _a_frame((200, 30, 30))
    row = _derives_in_a_play(client, sandbox, VISITOR_A, example, collection, clip, frame)

    sent = sandbox["runs"]["a"]["media_dir"]
    assert sent == str(media_dirs.media_work_root(GUEST_KEY)), sent
    read = _original(client, VISITOR_B, collection, row["file_id"])
    assert (read.status_code, read.data == frame) == (200, True), read.status_code
