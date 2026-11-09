"""A collection read in place from a bucket the deployment mounts, as node code
reads it: each row's ``path`` is the mount's folder (``root``) joined with what
every path in the mount starts with (``tail``) and the row's relpath, and a
mount that is down makes ``curio_load_collection`` raise why (``unavailable``).
The ``/exec`` route keeps both keys, in process and on the isolated path, which
hands them to the child as they are.

New names are imported inside the tests, so a checkout without them fails
each test on its own.
"""

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

import pytest

from utk_curio.sandbox.tests.test_collection_helpers import ROWS, write_index
from utk_curio.sandbox.tests.test_fetched_model_weights import isolated  # noqa: F401 - a fixture

ROOT = "/bucket-mounts/source.example.walks@1"
TAIL = "img_"
DOWN = "the mount service is down"
#: Each row's file in the mount: ROWS' relpaths, after the tail.
IN_THE_MOUNT = [
    os.path.join(ROOT, "img_2024", "x.jpg"),
    os.path.join(ROOT, "img_clip.mp4"),
    os.path.join(ROOT, "img_n.wav"),
]


def _load(collections, index):
    from utk_curio.sandbox.util.collections import make_collection_helpers

    return make_collection_helpers(lambda _id: str(index), collections, None)["curio_load_collection"]("c1")


def test_each_rows_path_is_the_mounts_folder_its_tail_and_its_relpath(tmp_path):
    index = write_index(tmp_path / "index.parquet", ROWS)

    frame = _load({"c1": {"root": ROOT, "tail": TAIL, "kind": "media"}}, index)

    assert frame["path"].tolist() == IN_THE_MOUNT


def test_a_relpath_that_leaves_the_mount_has_no_path_whatever_the_tail(tmp_path):
    rows = ROWS + [{"file_id": "d" * 16, "relpath": "../outside.jpg", "name": "outside.jpg",
                    "ext": "jpg", "kind": "image"}]
    index = write_index(tmp_path / "index.parquet", rows)

    frame = _load({"c1": {"root": ROOT, "tail": TAIL, "kind": "media"}}, index)

    assert frame["path"].tolist() == IN_THE_MOUNT + [None]


def test_a_mount_that_is_down_makes_curio_load_collection_say_why(tmp_path):
    index = write_index(tmp_path / "index.parquet", ROWS)

    with pytest.raises(RuntimeError, match=f"read in place from its bucket, which cannot be read now: {DOWN}"):
        _load({"c1": {"unavailable": DOWN, "kind": "media"}}, index)


class TestInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db

        _worker_init()
        init_db()

    def _exec(self, entry):
        from utk_curio.sandbox.app import app

        with tempfile.TemporaryDirectory() as tmp:
            index = write_index(Path(tmp) / "index.parquet", ROWS)
            return app.test_client().post("/exec", json={
                "code": textwrap.indent(
                    'for path in curio_load_collection("imported.xcol")["path"]:\n'
                    '    print(path)\n'
                    'return 1\n',
                    "    ",
                ),
                "file_path": "",
                "nodeType": "PYTHON_COMPUTATION",
                "dataType": "",
                "save_dataset": False,
                "dataset_paths": {"imported.xcol": str(index)},
                "collections": {"imported.xcol": entry},
            }).get_json()

    def test_the_route_keeps_a_mounted_collections_tail(self):
        body = self._exec({"root": ROOT, "tail": TAIL, "kind": "media"})

        self.assertEqual(body["stderr"], "", body)
        self.assertEqual(body["stdout"], IN_THE_MOUNT)

    def test_the_route_keeps_why_a_mount_is_down(self):
        body = self._exec({"unavailable": DOWN, "kind": "media"})

        self.assertIn(f"which cannot be read now: {DOWN}", body["stderr"])
        self.assertEqual(body["stdout"], [])


def test_the_isolated_path_hands_the_child_each_entrys_tail_and_why_its_mount_is_down(isolated, tmp_path):  # noqa: F811
    from utk_curio.sandbox.app import app

    handed, _copied = isolated
    index = write_index(tmp_path / "index.parquet", ROWS)
    collections = {
        "imported.xa": {"root": ROOT, "tail": TAIL, "kind": "media"},
        "imported.xb": {"unavailable": DOWN, "kind": "media"},
    }

    resp = app.test_client().post("/exec", json={
        "code": "    return 1\n",
        "file_path": "",
        "nodeType": "PYTHON_COMPUTATION",
        "dataType": "",
        "session_id": "session-mounted-collections",
        "save_dataset": False,
        "dataset_paths": {"imported.xa": str(index), "imported.xb": str(index)},
        "collections": collections,
    })
    resp.get_data(as_text=True)
    resp.close()

    request, _files = handed[-1]
    assert request["collections"] == collections


def test_the_isolated_child_reads_each_row_in_the_mount(tmp_path):
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.tests.test_isolation_child import namespace_factory, request

    write_index(tmp_path / "ds_0.parquet", ROWS)

    manifest = child.run_node(request(
        '    return "|".join(curio_load_collection("imported.xcol")["path"])\n',
        tmp_path,
        dataset_paths={"imported.xcol": "ds_0.parquet"},
        collections={"imported.xcol": {"root": ROOT, "tail": TAIL, "kind": "media"}},
        media_dir=str(tmp_path / "media"),
    ), namespace_factory)

    assert manifest["ok"], manifest
    assert manifest["output"]["value"] == "|".join(IN_THE_MOUNT)
