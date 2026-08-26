"""The isolated path accepts every input shape the in-process path does.

A merge output reaches a code node in two shapes, both documented on
``worker._expand_outputs_wrapper``:

* **live** -- a list literal of ``{'path': id}`` dicts.
* **reloaded** -- when the upstream merge output was persisted (a project save,
  or the JS-node round trip through DuckDB), the node receives a single bare ref
  to the stored ``{'dataType': 'outputs', 'data': [refs]}`` envelope.

``_build_input_spec`` handled only the first. It ``eval``'d the second as a
Python expression, so an artifact id like ``1787698132616_820e772c`` -- a
decimal literal followed by a name -- raised ``SyntaxError: invalid decimal
literal`` and the node failed before running. Found by the isolated CI job
running Merge.json, which no unit test covered.

Run:  pytest utk_curio/sandbox/tests/test_isolation_input_shapes.py -v
"""

import unittest
from unittest import mock

from utk_curio.sandbox.isolation import runner

LIVE = "[{'path': 'a1'}, {'path': 'b2'}]"
RELOADED = "1787698132616_820e772c"


class TestParseOutputsRefs(unittest.TestCase):
    """Which shape is this? Answered without touching the store."""

    def test_a_list_literal_is_a_list_of_refs(self):
        self.assertEqual(
            runner._parse_outputs_refs(LIVE),
            [{"path": "a1"}, {"path": "b2"}],
        )

    def test_a_bare_artifact_id_is_not(self):
        """The regression: this used to raise SyntaxError from eval."""
        self.assertIsNone(runner._parse_outputs_refs(RELOADED))

    def test_an_id_that_looks_like_a_number_is_not_evaluated(self):
        """Ids are digits and underscores; Python reads those as literals."""
        for art_id in ("1787698132616_820e772c", "123_456", "1e5_abc"):
            with self.subTest(art_id=art_id):
                self.assertIsNone(runner._parse_outputs_refs(art_id))

    def test_whitespace_does_not_hide_a_list(self):
        self.assertEqual(runner._parse_outputs_refs("  ['a1']  "), ["a1"])

    def test_empty_input_is_not_a_list(self):
        self.assertIsNone(runner._parse_outputs_refs(""))
        self.assertIsNone(runner._parse_outputs_refs(None))


class TestBuildInputSpec(unittest.TestCase):
    """Each shape reaches the staging call the in-process path would make."""

    def setUp(self):
        # Patch the attribute on the package, not sys.modules: the function
        # under test does `from utk_curio.sandbox.util import staging`, which
        # reads the attribute once the package is imported, so a sys.modules
        # entry is ignored whenever another test imported it first.
        from utk_curio.sandbox import util

        self.staging = mock.MagicMock()
        patcher = mock.patch.object(util, "staging", self.staging)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_live_shape_stages_the_list(self):
        runner._build_input_spec(LIVE, "outputs", "/scratch", "s1")

        self.staging.stage_outputs_list.assert_called_once_with(
            [{"path": "a1"}, {"path": "b2"}], "/scratch", session_id="s1"
        )

    def test_the_reloaded_shape_is_expanded_then_staged(self):
        """The child must get the per-slot list, not the wrapper dict.

        Staging the envelope as a plain artifact would hand user code the
        wrapper object -- the exact bug _expand_outputs_wrapper prevents
        in-process ("arg is not iterable").
        """
        self.staging.read_outputs_wrapper.return_value = [{"path": "a1"}]

        runner._build_input_spec(RELOADED, "outputs", "/scratch", "s1")

        self.staging.read_outputs_wrapper.assert_called_once_with(
            RELOADED, session_id="s1"
        )
        self.staging.stage_outputs_list.assert_called_once_with(
            [{"path": "a1"}], "/scratch", session_id="s1"
        )
        self.staging.stage_input.assert_not_called()

    def test_an_outputs_ref_holding_something_else_is_staged_as_it_is(self):
        """Permissive, like the in-process path: degrade, do not fail."""
        self.staging.read_outputs_wrapper.return_value = None

        runner._build_input_spec(RELOADED, "outputs", "/scratch", "s1")

        self.staging.stage_input.assert_called_once_with(
            RELOADED, "/scratch", session_id="s1", slot="in_0"
        )

    def test_a_plain_input_is_unaffected(self):
        runner._build_input_spec("art-9", "dataframe", "/scratch", "s1")

        self.staging.stage_input.assert_called_once_with(
            "art-9", "/scratch", session_id="s1", slot="in_0"
        )
        self.staging.stage_outputs_list.assert_not_called()

    def test_no_input_stages_nothing(self):
        spec = runner._build_input_spec("", "str", "/scratch", "s1")

        self.assertEqual(spec["kind"], "none")
        self.staging.stage_input.assert_not_called()


class TestTheChildRunsInTheLaunchDirectory(unittest.TestCase):
    """Relative paths in node code must resolve where they do in-process.

    The bundled examples read their data relatively
    (``gpd.read_file("docs/examples/data/access_score.geojson")``), and
    ``confine`` used to chdir into the scratch directory, so every one of them
    failed with "No such file or directory" -- not a permissions failure: the
    child could read the file, it was looking in the wrong place.
    """

    def test_the_request_carries_the_work_directory(self):
        from utk_curio.sandbox.isolation import protocol

        request = protocol.build_exec_request(
            code="pass",
            node_type="t",
            data_type="str",
            scratch_dir="/scratch/exec-1",
            input_spec={"kind": "none"},
            work_dir="/app",
        )
        self.assertEqual(request["work_dir"], "/app")
        self.assertEqual(request["scratch_dir"], "/scratch/exec-1")

    def test_a_request_without_one_is_still_valid(self):
        """An older parent, or a caller that has no launch dir to give."""
        from utk_curio.sandbox.isolation import protocol

        request = protocol.build_exec_request(
            code="pass",
            node_type="t",
            data_type="str",
            scratch_dir="/scratch/exec-1",
            input_spec={"kind": "none"},
        )
        self.assertIsNone(request["work_dir"])


if __name__ == "__main__":
    unittest.main()
