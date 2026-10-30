"""#332: the user's node libraries reach the child, and only the child.

The parent picks the directory (it is the only side that knows who is logged
in), the wire carries it, and the child puts it on ``sys.path`` after the fork.
That last part is the whole boundary: a path installed in the zygote would be
on every subsequent user's path, because the zygote is forked once per
execution for whoever asks next.

Run:  pytest utk_curio/sandbox/tests/test_isolation_overlay_path.py -v
"""

import json
import os
import sys
import tempfile
import unittest

from utk_curio.sandbox.isolation import child, protocol


class TestTheWireCarriesIt(unittest.TestCase):

    def _request(self, **kw):
        return protocol.build_exec_request(
            code="return 1", node_type="n", data_type="str",
            scratch_dir="/tmp/scratch", input_spec={"kind": "none"}, **kw,
        )

    def test_the_overlay_is_part_of_the_request(self):
        request = self._request(overlay_dir="/srv/.curio/exec-overlays/users/7")
        self.assertEqual(
            request["overlay_dir"], "/srv/.curio/exec-overlays/users/7",
        )

    def test_no_overlay_is_a_shared_interpreter(self):
        """What an unisolated instance means, and what an older parent sends."""
        self.assertIsNone(self._request()["overlay_dir"])


class TestTheChildPutsItOnThePath(unittest.TestCase):

    def setUp(self):
        self._path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), self._path))

    def test_it_is_prepended_so_the_users_own_copy_wins(self):
        with tempfile.TemporaryDirectory() as overlay:
            child._add_overlay_to_path(overlay)
            self.assertEqual(sys.path[0], overlay)

    def test_none_changes_nothing(self):
        child._add_overlay_to_path(None)
        self.assertEqual(sys.path, self._path)

    def test_a_directory_that_does_not_exist_changes_nothing(self):
        """A user with nothing installed is not an error."""
        child._add_overlay_to_path("/nonexistent/exec-overlays/users/7")
        self.assertEqual(sys.path, self._path)

    def test_it_is_not_added_twice(self):
        with tempfile.TemporaryDirectory() as overlay:
            child._add_overlay_to_path(overlay)
            child._add_overlay_to_path(overlay)
            self.assertEqual(sys.path.count(overlay), 1)

    def test_an_unreadable_overlay_does_not_refuse_the_node(self):
        """It fails later as a plain ImportError naming the library, which is
        the message that helps. Refusing to run says nothing useful."""
        def _boom(_path):
            raise OSError("permission denied")

        original = os.path.isdir
        os.path.isdir = _boom
        try:
            child._add_overlay_to_path("/srv/.curio/exec-overlays/users/7")
        finally:
            os.path.isdir = original
        self.assertEqual(sys.path, self._path)


class TestAnEditorsRunReadsTheOwnersLibrariesToo(unittest.TestCase):
    """A run of an editor the dataflow's owner invited: his folder, then hers,
    which the child only reads. On the path in that order, so his own copy of
    a library wins (``test_isolation_library_keys.py`` has the parent's half)."""

    def setUp(self):
        self._path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), self._path))

    def _on_the_wire(self, overlay_dir):
        """The request's overlay as the child reads it, past the socket's JSON."""
        request = protocol.build_exec_request(
            code="return 1", node_type="n", data_type="str",
            scratch_dir="/tmp/scratch", input_spec={"kind": "none"}, overlay_dir=overlay_dir,
        )
        return json.loads(json.dumps(request))["overlay_dir"]

    def test_the_request_carries_both_folders_in_order(self):
        folders = ["/srv/.curio/exec-overlays/users/8", "/srv/.curio/exec-overlays/users/7"]
        self.assertEqual(self._on_the_wire(folders), folders)

    def test_the_child_puts_both_on_the_path_his_first(self):
        with tempfile.TemporaryDirectory() as his, tempfile.TemporaryDirectory() as hers:
            child._add_overlay_to_path(self._on_the_wire([his, hers]))
            self.assertEqual(sys.path[:2], [his, hers])

    def test_a_folder_of_hers_that_does_not_exist_leaves_his_alone(self):
        """An owner who installed nothing."""
        with tempfile.TemporaryDirectory() as his:
            child._add_overlay_to_path(self._on_the_wire([his, "/nonexistent/exec-overlays/users/7"]))
            self.assertEqual(sys.path, [his, *self._path])


class TestItHappensAfterTheFork(unittest.TestCase):
    """The zygote is forked once per execution for whoever asks next, so a path
    installed there would be every user's path. This is the reason the overlay
    is applied in ``confine`` rather than at warm-up."""

    def test_the_zygote_never_reads_an_overlay(self):
        import pathlib

        source = pathlib.Path(
            "utk_curio/sandbox/isolation/zygote.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("overlay", source.lower())

    def test_confine_is_what_applies_it(self):
        import inspect

        self.assertIn("overlay_dir", inspect.signature(child.confine).parameters)
        body = inspect.getsource(child.confine)
        self.assertIn("_add_overlay_to_path(overlay_dir)", body)


if __name__ == "__main__":
    unittest.main()
