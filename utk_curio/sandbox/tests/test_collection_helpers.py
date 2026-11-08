"""``curio_load_collection`` and ``curio_derived_file``, in process and isolated.

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
        frame = self.helpers({"c1": {"root": "/srv/media"}})["curio_load_collection"]("c1")
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
        frame = self.helpers({"c1": {"root": "/srv/media"}})["curio_load_collection"]("c1")
        outside = frame[frame["file_id"] == "d" * 16].iloc[0]
        self.assertTrue(pd.isna(outside["path"]))

    def test_a_bucket_collection_has_a_path_only_once_cached(self):
        objects = self.tmp / "objects"
        objects.mkdir()
        (objects / f"{'a' * 16}.jpg").write_bytes(b"x")
        frame = self.helpers({"c1": {"objects": str(objects)}})["curio_load_collection"]("c1")
        self.assertEqual(frame.loc[0, "path"], str(objects / f"{'a' * 16}.jpg"))
        self.assertTrue(pd.isna(frame.loc[1, "path"]))

    def test_a_file_that_is_not_here_has_the_path_none(self):
        """A row's ``path`` is None for a file this execution cannot open, as
        documented, so ``if row["path"]:`` reads it as missing. pandas stores
        a column of strings with NaN for it, and NaN is truthy. The index has
        a ``bytes`` column, as every index ``index_collection`` writes does."""
        outside = {"file_id": "d" * 16, "relpath": "../outside.jpg", "name": "outside.jpg",
                   "ext": "jpg", "kind": "image"}
        write_index(self.index, [{**row, "bytes": 100} for row in ROWS + [outside]])
        objects = self.tmp / "objects"
        objects.mkdir()
        (objects / f"{'a' * 16}.jpg").write_bytes(b"x")
        cached = self.helpers({"c1": {"objects": str(objects)}})["curio_load_collection"]("c1")
        in_place = self.helpers({"c1": {"root": "/srv/media"}})["curio_load_collection"]("c1")
        self.assertEqual(
            {"uncached": cached["path"].tolist()[1:], "outside its root": in_place["path"].tolist()[3]},
            {"uncached": [None, None, None], "outside its root": None},
        )
        self.assertEqual(cached["path"].tolist()[0], str(objects / f"{'a' * 16}.jpg"))
        self.assertEqual([bool(row["path"]) for _, row in cached.iterrows()], [True, False, False, False])

    def test_an_index_with_positions_is_a_geodataframe(self):
        write_index(self.index, ROWS, geo=True)
        frame = self.helpers({"c1": {"root": "/r"}})["curio_load_collection"]("c1")
        self.assertIsInstance(frame, gpd.GeoDataFrame)

    def test_an_unresolved_collection_says_what_to_do(self):
        with self.assertRaisesRegex(RuntimeError, "Discovery Catalog"):
            self.helpers({})["curio_load_collection"]("missing")

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

    def test_a_tag_tells_two_derived_files_of_one_file_and_time_apart(self):
        """An overlay names the model that drew it (#621), so two models'
        overlays of one photo are two files."""
        media = self.tmp / "media"
        derive = self.helpers({}, str(media))["curio_derived_file"]
        row = derive("c1", "b" * 16, 0, "png", kind="image", tag="0a1b2c3d4e5f")
        self.assertEqual(row["file_id"], f"{'b' * 16}@0-0a1b2c3d4e5f")
        self.assertEqual(Path(row["path"]), media / "overlays" / "c1" / ("b" * 16) / "0-0a1b2c3d4e5f.png")
        self.assertTrue(row["image_url"].endswith(f"/media/{'b' * 16}@0-0a1b2c3d4e5f?variant=original"))
        other = derive("c1", "b" * 16, 0, "png", kind="image", tag="ffff")
        self.assertNotEqual(other["path"], row["path"])
        for bad in ("../x", "a/b", "A", "x" * 33, ""):
            with self.subTest(tag=bad), self.assertRaises(ValueError):
                derive("c1", "b" * 16, 0, "png", kind="image", tag=bad)

    def test_a_derived_file_refuses_ids_that_are_not_ids(self):
        derive = self.helpers({}, str(self.tmp))["curio_derived_file"]
        with self.assertRaises(ValueError):
            derive("c1", "../../etc", 1)
        with self.assertRaises(ValueError):
            derive("../c1", "a" * 16, 1)

    def test_a_video_made_from_a_video_has_a_folder_and_an_id_of_its_own(self):
        """An overlay MP4 a node writes from a video, as Track Objects will:
        its row is a video's, which Simple View plays from its ids, and its id
        is not the frame's at the same time and tag."""
        media = self.tmp / "media"
        derive = self.helpers({}, str(media))["curio_derived_file"]
        row = derive("c1", "b" * 16, 0, "mp4", tag="sam3")
        self.assertEqual(Path(row["path"]), media / "videos" / "c1" / ("b" * 16) / "0-sam3.mp4")
        self.assertTrue(Path(row["path"]).parent.is_dir())
        # A collection's video's columns: its image is its thumbnail, a poster.
        thumb = f"/api/datasets/c1/media/{'b' * 16}@0-sam3.mp4?variant=thumb"
        self.assertEqual(
            {k: row[k] for k in ("file_id", "dataset_id", "kind", "thumbnail", "image_url", "audio_url")},
            {"file_id": f"{'b' * 16}@0-sam3.mp4", "dataset_id": "c1", "kind": "video",
             "thumbnail": thumb, "image_url": thumb, "audio_url": None},
        )
        frame = derive("c1", "b" * 16, 0, tag="sam3")
        self.assertEqual((frame["file_id"], frame["kind"]), (f"{'b' * 16}@0-sam3", "frame"))
        self.assertEqual(Path(frame["path"]), media / "frames" / "c1" / ("b" * 16) / "0-sam3.jpg")

    def test_a_table_found_in_a_video_has_a_path_and_no_media_url(self):
        """What Track Objects keeps of a video's tracks: a Parquet that later
        nodes read by its path, and that the media route serves nothing of."""
        media = self.tmp / "media"
        row = self.helpers({}, str(media))["curio_derived_file"]("c1", "b" * 16, 0, "parquet", tag="sam3")
        self.assertEqual(Path(row["path"]), media / "tables" / "c1" / ("b" * 16) / "0-sam3.parquet")
        self.assertTrue(Path(row["path"]).parent.is_dir())
        self.assertEqual(
            {k: row[k] for k in ("file_id", "dataset_id", "kind", "thumbnail", "image_url", "audio_url")},
            {"file_id": f"{'b' * 16}@0-sam3.parquet", "dataset_id": "c1", "kind": "table",
             "thumbnail": None, "image_url": None, "audio_url": None},
        )

    def test_every_derived_row_has_a_collection_rows_locator_columns(self):
        """Each derived row says what it is (``kind``) and whose it is
        (``dataset_id``), as a collection's row does, so Simple View plays a
        video's row by its ids, and a derived row put over its file's row
        (``{**video, **overlay}``) leaves none of the file's own addresses
        behind. One assertion over every type, so each counts in this test."""
        derive = self.helpers({}, str(self.tmp / "media"))["curio_derived_file"]
        columns = sorted(("file_id", "dataset_id", "kind", "path", "thumbnail", "image_url", "audio_url"))
        made = {
            (kind, ext): derive("c1", "b" * 16, 0, ext, kind=kind, tag="m1")
            for kind, ext in (("video", None), ("video", "mp4"), ("video", "png"), ("video", "parquet"),
                              ("audio", None), ("image", None), ("frame", None))
        }
        self.assertEqual(
            {made_as: (sorted(row), row.get("kind"), row.get("dataset_id")) for made_as, row in made.items()},
            {
                ("video", None): (columns, "frame", "c1"), ("video", "mp4"): (columns, "video", "c1"),
                ("video", "png"): (columns, "image", "c1"), ("video", "parquet"): (columns, "table", "c1"),
                ("audio", None): (columns, "audio", "c1"), ("image", None): (columns, "image", "c1"),
                ("frame", None): (columns, "image", "c1"),
            },
        )

    def test_an_overlay_of_a_sequences_frame_goes_where_a_photos_does(self):
        """Image Segmentation names any image's overlay with kind image; a
        frames collection's file is kind frame, which the media route reads."""
        derive = self.helpers({}, str(self.tmp / "media"))["curio_derived_file"]
        as_image = derive("c1", "d" * 16, 0, "png", kind="image", tag="m1")
        as_frame = derive("c1", "d" * 16, 0, "png", kind="frame", tag="m1")
        self.assertEqual((as_frame["path"], as_frame["file_id"]), (as_image["path"], as_image["file_id"]))

    def test_what_the_media_route_would_never_find_is_refused_and_nothing_is_made(self):
        """A file a kind does not derive (``DERIVED``), or at a time no id
        holds, would be written and never served: its row's links would fail.
        One assertion over every case, so each counts in this test."""
        media = self.tmp / "media"
        derive = self.helpers({}, str(media))["curio_derived_file"]
        cases = {
            "a video made from a recording": lambda: derive("c1", "c" * 16, 0, "mp4", kind="audio"),
            "a video made from a photo": lambda: derive("c1", "a" * 16, 0, "mp4", kind="image"),
            "a format no kind derives": lambda: derive("c1", "b" * 16, 0, "txt"),
            "a frame's format, upper case": lambda: derive("c1", "b" * 16, 0, "JPG"),
            "a kind nothing is derived from": lambda: derive("c1", "b" * 16, 0, kind="raster"),
            "a time before the file starts": lambda: derive("c1", "b" * 16, -1, "mp4", tag="sam3"),
            "a time longer than an id holds": lambda: derive("c1", "b" * 16, 10**12, "mp4", tag="sam3"),
            "a video's tag that is no tag": lambda: derive("c1", "b" * 16, 0, "mp4", tag="SAM3"),
        }
        outcomes = {}
        for case, call in cases.items():
            try:
                outcomes[case] = f"named {call()['path']}"
            except ValueError:
                outcomes[case] = "refused"
        self.assertEqual(outcomes, {case: "refused" for case in cases})
        self.assertFalse(media.exists())

    def test_without_a_media_directory_there_is_nowhere_to_write(self):
        with self.assertRaisesRegex(RuntimeError, "curio_load_collection"):
            self.helpers({}, None)["curio_derived_file"]("c1", "a" * 16, 1)


class TestInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db

        _worker_init()
        init_db()

    def test_the_exec_route_injects_curio_load_collection(self):
        from utk_curio.sandbox.app import app

        with tempfile.TemporaryDirectory() as tmp:
            index = write_index(Path(tmp) / "index.parquet", ROWS)
            response = app.test_client().post("/exec", json={
                "code": (
                    '    frame = curio_load_collection("imported.xcol")\n'
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
                '    return len(curio_load_collection("imported.xcol"))\n',
                scratch,
                dataset_paths={"imported.xcol": "ds_0.parquet"},
                collections={"imported.xcol": {"root": "/srv/media"}},
                media_dir=str(scratch / "media"),
            ), namespace_factory)
            self.assertTrue(manifest["ok"], manifest)
            self.assertEqual(manifest["output"]["value"], 3)


if __name__ == "__main__":
    unittest.main()
