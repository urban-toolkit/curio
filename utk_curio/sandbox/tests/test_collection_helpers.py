"""``curio_collection`` and ``curio_derived_file``, in process and isolated.

A collection's index is a dataset like any other, so it reaches the sandbox
through the same ``dataset_paths`` mapping (staged into scratch when
isolated). What is new is where each file is: the backend sends a folder
collection's root or a bucket collection's cache directory, and the helper
turns every row's relpath into a path this execution can open.
"""

import os
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from utk_curio.sandbox.util.collections import make_collection_helpers


def write_index(path, rows, *, geo=False):
    frame = pd.DataFrame(rows)
    if geo:
        gpd.GeoDataFrame(frame, geometry=[Point(0, 0)] * len(frame), crs=4326).to_parquet(path)
    else:
        frame.to_parquet(path, index=False)
    return path


ROWS = [
    {"file_id": "a" * 16, "relpath": "2024/x.jpg", "name": "x.jpg", "ext": "jpg", "kind": "image"},
    {"file_id": "b" * 16, "relpath": "clip.mp4", "name": "clip.mp4", "ext": "mp4", "kind": "video"},
    {"file_id": "c" * 16, "relpath": "n.wav", "name": "n.wav", "ext": "wav", "kind": "audio"},
]


class TestTheHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.index = write_index(self.tmp / "index.parquet", ROWS)

    def tearDown(self):
        self._tmp.cleanup()

    def helpers(self, collections, media_dir=None):
        return make_collection_helpers(lambda _id: str(self.index), collections, media_dir)

    def test_a_folder_collection_resolves_every_row_under_its_root(self):
        frame = self.helpers({"c1": {"root": "/srv/media"}})["curio_collection"]("c1")
        self.assertEqual(frame.loc[0, "path"], os.path.join("/srv/media", "2024", "x.jpg"))
        self.assertEqual(set(frame["dataset_id"]), {"c1"})
        self.assertEqual(frame.loc[0, "thumbnail"], f"/api/datasets/c1/media/{'a' * 16}?variant=thumb")
        self.assertEqual(frame.loc[0, "image_url"], f"/api/datasets/c1/media/{'a' * 16}?variant=original")
        self.assertEqual(frame.loc[1, "image_url"], f"/api/datasets/c1/media/{'b' * 16}?variant=thumb")
        self.assertTrue(pd.isna(frame.loc[0, "audio_url"]))
        self.assertEqual(frame.loc[2, "audio_url"], f"/api/datasets/c1/media/{'c' * 16}?variant=original")

    def test_a_row_that_leaves_its_root_has_no_path(self):
        rows = ROWS + [{"file_id": "d" * 16, "relpath": "../outside.jpg", "name": "outside.jpg",
                        "ext": "jpg", "kind": "image"}]
        write_index(self.index, rows)
        frame = self.helpers({"c1": {"root": "/srv/media"}})["curio_collection"]("c1")
        outside = frame[frame["file_id"] == "d" * 16].iloc[0]
        self.assertTrue(pd.isna(outside["path"]))

    def test_a_bucket_collection_has_a_path_only_once_cached(self):
        objects = self.tmp / "objects"
        objects.mkdir()
        (objects / f"{'a' * 16}.jpg").write_bytes(b"x")
        frame = self.helpers({"c1": {"objects": str(objects)}})["curio_collection"]("c1")
        self.assertEqual(frame.loc[0, "path"], str(objects / f"{'a' * 16}.jpg"))
        self.assertTrue(pd.isna(frame.loc[1, "path"]))

    def test_an_index_with_positions_is_a_geodataframe(self):
        write_index(self.index, ROWS, geo=True)
        frame = self.helpers({"c1": {"root": "/r"}})["curio_collection"]("c1")
        self.assertIsInstance(frame, gpd.GeoDataFrame)

    def test_an_unresolved_collection_says_what_to_do(self):
        with self.assertRaisesRegex(RuntimeError, "Data Lake Catalog"):
            self.helpers({})["curio_collection"]("missing")

    def test_a_derived_file_is_named_and_its_folder_made(self):
        media = self.tmp / "media"
        row = self.helpers({}, str(media))["curio_derived_file"]("c1", "b" * 16, 2000)
        self.assertEqual(row["file_id"], f"{'b' * 16}@2000")
        self.assertEqual(Path(row["path"]), media / "frames" / "c1" / ("b" * 16) / "2000.jpg")
        self.assertTrue(Path(row["path"]).parent.is_dir())
        self.assertIn("variant=thumb", row["thumbnail"])
        clip = self.helpers({}, str(media))["curio_derived_file"]("c1", "c" * 16, 5000, kind="audio")
        self.assertTrue(clip["path"].endswith(os.path.join("clips", "c1", "c" * 16, "5000.wav")))
        self.assertIn("audio_url", clip)

    def test_a_derived_file_refuses_ids_that_are_not_ids(self):
        derive = self.helpers({}, str(self.tmp))["curio_derived_file"]
        with self.assertRaises(ValueError):
            derive("c1", "../../etc", 1)
        with self.assertRaises(ValueError):
            derive("../c1", "a" * 16, 1)

    def test_without_a_media_directory_there_is_nowhere_to_write(self):
        with self.assertRaisesRegex(RuntimeError, "curio_collection"):
            self.helpers({}, None)["curio_derived_file"]("c1", "a" * 16, 1)


class TestInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db

        _worker_init()
        init_db()

    def test_the_exec_route_injects_curio_collection(self):
        from utk_curio.sandbox.app import app

        with tempfile.TemporaryDirectory() as tmp:
            index = write_index(Path(tmp) / "index.parquet", ROWS)
            response = app.test_client().post("/exec", json={
                "code": (
                    '    frame = curio_collection("imported.xcol")\n'
                    '    return frame.loc[0, "path"]\n'
                ),
                "file_path": "",
                "nodeType": "PYTHON_COMPUTATION",
                "dataType": "",
                "save_dataset": False,
                "dataset_paths": {"imported.xcol": str(index)},
                "collections": {"imported.xcol": {"root": "/srv/media", "kind": "media"}},
            })
            body = response.get_json()
            self.assertEqual(body["stderr"], "", body)
            self.assertEqual(body["output"]["dataType"], "str")


class TestIsolatedChild(unittest.TestCase):
    def test_the_child_reads_the_staged_index(self):
        from utk_curio.sandbox.isolation import child
        from utk_curio.sandbox.tests.test_isolation_child import namespace_factory, request

        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_index(scratch / "ds_0.parquet", ROWS)
            manifest = child.run_node(request(
                '    return len(curio_collection("imported.xcol"))\n',
                scratch,
                dataset_paths={"imported.xcol": "ds_0.parquet"},
                collections={"imported.xcol": {"root": "/srv/media"}},
                media_dir=str(scratch / "media"),
            ), namespace_factory)
            self.assertTrue(manifest["ok"], manifest)
            self.assertEqual(manifest["output"]["value"], 3)


if __name__ == "__main__":
    unittest.main()
