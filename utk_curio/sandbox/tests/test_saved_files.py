"""``curio_save_file``, ``curio_save_folder`` and ``curio_computed_path``.

A node saves a file or a folder under a name; the backend installs it as the
computed dataset ``computed.<dataflowId>.files.<name>`` and sends a later
run the name with its resolved dataset id. In process the files are written
beside the artifacts; an isolated child writes them under ``<scratch>/saved``,
and the parent copies them out, refusing anything but regular files.
"""

import os
import tempfile
import unittest
from pathlib import Path

from utk_curio.sandbox.util.saved_files import (
    collect_saved,
    describe_saved,
    make_saved_helpers,
)

CAN_SAVE = {"canSave": True}


def no_path(dataset_id):
    raise AssertionError(f"no dataset path expected, asked for {dataset_id}")


class TestSaving(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "saved"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_file_is_written_under_its_name_and_described(self):
        helpers, saved = make_saved_helpers(self.root, no_path, CAN_SAVE)
        path = helpers["curio_save_file"]("summary.csv")
        self.assertEqual(Path(path), self.root / "summary" / "summary.csv")
        Path(path).write_text("a,b\n1,2\n")
        self.assertEqual(describe_saved(saved, self.root), [
            {"name": "summary", "kind": "file", "file": "summary.csv", "path": path},
        ])

    def test_a_folder_is_empty_and_holds_any_files(self):
        helpers, saved = make_saved_helpers(self.root, no_path, CAN_SAVE)
        folder = Path(helpers["curio_save_folder"]("tiles"))
        self.assertEqual(list(folder.iterdir()), [])
        (folder / "16_1_2.png").write_bytes(b"png")
        (folder / "16").mkdir()
        [entry] = describe_saved(saved, self.root)
        self.assertEqual((entry["name"], entry["kind"], entry["path"]), ("tiles", "folder", str(folder)))

    def test_a_file_never_written_is_not_described(self):
        helpers, saved = make_saved_helpers(self.root, no_path, CAN_SAVE)
        helpers["curio_save_file"]("summary.csv")
        self.assertEqual(describe_saved(saved, self.root), [])

    def test_names_are_one_lowercase_segment(self):
        helpers, _ = make_saved_helpers(self.root, no_path, CAN_SAVE)
        for bad in ("Tiles", "1tiles", "my_tiles", "a/b", "", "a.b"):
            with self.assertRaises(ValueError, msg=bad):
                helpers["curio_save_folder"](bad)
        for bad in ("summary", "Summary.csv", "../x.csv", "summary.png"):
            with self.assertRaises(ValueError, msg=bad):
                helpers["curio_save_file"](bad)

    def test_a_name_is_saved_once_per_run(self):
        helpers, _ = make_saved_helpers(self.root, no_path, CAN_SAVE)
        helpers["curio_save_folder"]("tiles")
        with self.assertRaises(ValueError):
            helpers["curio_save_file"]("tiles.csv")

    def test_saving_is_refused_with_the_backends_reason(self):
        helpers, _ = make_saved_helpers(self.root, no_path, {"canSave": False, "reason": "Save the dataflow first."})
        with self.assertRaisesRegex(RuntimeError, "Save the dataflow first"):
            helpers["curio_save_file"]("summary.csv")
        self.assertFalse(self.root.exists())


class TestReading(unittest.TestCase):
    def test_a_file_is_its_dataset_path(self):
        paths = {"computed.df1.files.summary": "/store/computed.df1.files.summary@1/data/summary.csv"}
        helpers, _ = make_saved_helpers("/unused", paths.__getitem__, {"names": {"summary": "computed.df1.files.summary"}})
        self.assertEqual(helpers["curio_computed_path"]("summary"), paths["computed.df1.files.summary"])

    def test_a_folder_is_the_files_beside_its_bundle(self):
        bundle = "/store/computed.df1.files.tiles@1/data/bundle.json"
        helpers, _ = make_saved_helpers("/unused", lambda _id: bundle, {"names": {"tiles": "computed.df1.files.tiles"}})
        self.assertEqual(helpers["curio_computed_path"]("tiles"), "/store/computed.df1.files.tiles@1/data/files")

    def test_a_name_nothing_saved_says_how_to_save_it(self):
        helpers, _ = make_saved_helpers("/unused", no_path, {})
        with self.assertRaisesRegex(FileNotFoundError, r'curio_save_folder\("tiles"\)'):
            helpers["curio_computed_path"]("tiles")


class TestCollectingFromAnIsolatedChild(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.scratch = Path(self._tmp.name) / "scratch"
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_files_and_folders_are_copied_out_and_links_refused(self):
        helpers, _ = make_saved_helpers(self.scratch / "saved", no_path, CAN_SAVE)
        Path(helpers["curio_save_file"]("summary.csv")).write_text("a\n1\n")
        folder = Path(helpers["curio_save_folder"]("tiles"))
        (folder / "16").mkdir()
        (folder / "16" / "1_2.png").write_bytes(b"png")
        secret = Path(self._tmp.name) / "secret.txt"
        secret.write_text("not yours")
        os.symlink(secret, folder / "leak.txt")

        entries = {e["name"]: e for e in collect_saved(self.scratch, self.data)}

        self.assertEqual(set(entries), {"summary", "tiles"})
        self.assertEqual(Path(entries["summary"]["path"]).read_text(), "a\n1\n")
        copied = Path(entries["tiles"]["path"])
        self.assertTrue(str(copied).startswith(str(self.data)))
        self.assertEqual(sorted(p.relative_to(copied).as_posix() for p in copied.rglob("*") if p.is_file()), ["16/1_2.png"])

    def test_nothing_saved_is_nothing_collected(self):
        self.assertEqual(collect_saved(self.scratch, self.data), [])


if __name__ == "__main__":
    unittest.main()
