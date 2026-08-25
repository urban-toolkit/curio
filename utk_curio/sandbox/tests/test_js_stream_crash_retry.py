"""A crash inside Node's own HTTP parser is retried; nothing else is.

``execute_js_code`` used to hand every non-zero Node exit straight back to the
user as node stderr. That is right for user-code errors, and wrong for one
failure mode: undici's parser asserts (``assert(!this.paused)``) when the
response socket ends while it is paused for backpressure, which aborts the
process from inside an internal event handler. The run produces no result and no
diagnosis, and the same node succeeds when run again - the OSM examples hit it
because ``@urban-toolkit/autk-db`` awaits a callback per PBF block while
streaming the file over HTTP.

What matters here is the *narrowness*: a retry that fires on ordinary failures
would double the cost of every genuinely failing node, and could re-run side
effects the first attempt already performed. Most of these tests are therefore
about what does NOT retry.

Run:  pytest utk_curio/sandbox/tests/test_js_stream_crash_retry.py -v
"""

import unittest
from unittest import mock

from utk_curio.sandbox.app.worker import is_node_internal_stream_crash

# The stderr Node actually produced, trimmed to the lines the check reads.
UNDICI_CRASH_STDERR = [
    "node:internal/assert/utils:77",
    "    throw err;",
    "    ^",
    "",
    "AssertionError [ERR_ASSERTION]: The expression evaluated to a falsy value:",
    "",
    "  assert(!this.paused)",
    "",
    "    at Parser.finish (node:internal/deps/undici/undici:7388:9)",
    "    at Socket.onHttpSocketEnd (node:internal/deps/undici/undici:7827:34)",
    "    at Socket.emit (node:events:521:24)",
    "Node.js v24.19.0",
]

RESULT_LINE = '__CURIO_JSON_RESULT__{"success": false, "error": "boom", "logs": []}'


class TestCrashDetection(unittest.TestCase):
    def test_the_undici_assertion_is_recognised(self):
        self.assertTrue(is_node_internal_stream_crash(1, [], UNDICI_CRASH_STDERR))

    def test_a_successful_run_is_not_a_crash(self):
        """Exit 0 short-circuits even if the text somehow appears in stderr."""
        self.assertFalse(is_node_internal_stream_crash(0, [], UNDICI_CRASH_STDERR))

    def test_a_run_that_produced_a_result_is_not_retried(self):
        """The wrapper reports user errors through the result line, at exit 0 or not.

        Retrying here would re-run a node whose outcome the user has already
        been told about.
        """
        self.assertFalse(
            is_node_internal_stream_crash(1, [RESULT_LINE], UNDICI_CRASH_STDERR)
        )

    def test_a_plain_user_error_is_not_retried(self):
        stderr = [
            "file:///tmp/x.mjs:3",
            "ReferenceError: notDefined is not defined",
            "    at file:///tmp/x.mjs:3:1",
        ]
        self.assertFalse(is_node_internal_stream_crash(1, [], stderr))

    def test_a_user_assertion_is_not_mistaken_for_it(self):
        """User code may assert too; only undici's own frame counts."""
        stderr = [
            "AssertionError [ERR_ASSERTION]: The expression evaluated to a falsy value:",
            "",
            "  assert(!this.paused)",
            "",
            "    at file:///app/user-node.mjs:12:3",
        ]
        self.assertFalse(is_node_internal_stream_crash(1, [], stderr))

    def test_an_empty_failure_is_not_retried(self):
        """A killed or OOM'd process leaves nothing to match on."""
        self.assertFalse(is_node_internal_stream_crash(137, [], []))


class TestRetryWiring(unittest.TestCase):
    """The detector is actually consulted, and drives exactly one re-run.

    ``execute_js_code`` is driven through a patched ``subprocess.Popen``: the
    first Node process crashes the way undici does, the second succeeds.
    """

    def _fake_popen(self, runs):
        """Return a Popen stand-in that replays *runs* (stdout, stderr, code)."""
        calls = []

        class _FakeProc:
            def __init__(self, stdout, stderr, returncode):
                import io as _io
                self.stdin = _io.StringIO()
                self.stdout = _io.StringIO(stdout)
                self.stderr = _io.StringIO(stderr)
                self.returncode = returncode

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                pass

        def _popen(*args, **kwargs):
            stdout, stderr, code = runs[len(calls)]
            calls.append(kwargs)
            return _FakeProc(stdout, stderr, code)

        return _popen, calls

    def _execute(self, popen):
        # `subprocess` and the parsers are imported inside execute_js_code, so
        # both are patched where they live rather than on the worker module.
        from utk_curio.sandbox.app import worker
        from utk_curio.sandbox.util import parsers

        with mock.patch('subprocess.Popen', popen), \
                mock.patch.object(parsers, 'save_to_duckdb', return_value='art-1'), \
                mock.patch.object(parsers, 'detect_kind', return_value='int'):
            return worker.execute_js_code(
                code="return 1;",
                file_path=None,
                node_type='curio.builtin/js-computation@1',
                data_type='str',
                save_dataset=False,
            )

    def test_the_crash_is_retried_once_and_the_retry_is_kept(self):
        ok = '__CURIO_JSON_RESULT__{"success": true, "value": 42, "logs": ["hi"]}\n'
        popen, calls = self._fake_popen([
            ('', '\n'.join(UNDICI_CRASH_STDERR) + '\n', 1),
            (ok, '', 0),
        ])
        result = self._execute(popen)

        self.assertEqual(len(calls), 2, "the crash should have produced a second run")
        self.assertEqual(result['stdout'], ["hi"])

    def test_a_user_error_runs_node_exactly_once(self):
        err = '__CURIO_JSON_RESULT__{"success": false, "error": "boom", "logs": []}\n'
        popen, calls = self._fake_popen([(err, '', 1)])
        result = self._execute(popen)

        self.assertEqual(len(calls), 1, "a user error must not be re-run")
        self.assertEqual(result['stderr'], "boom")

    def test_two_crashes_in_a_row_report_the_crash(self):
        """The retry is not a loop; a second failure is surfaced as-is."""
        crash = ('', '\n'.join(UNDICI_CRASH_STDERR) + '\n', 1)
        popen, calls = self._fake_popen([crash, crash])
        result = self._execute(popen)

        self.assertEqual(len(calls), 2)
        self.assertIn("assert(!this.paused)", result['stderr'])
        self.assertEqual(result['output']['path'], '')


if __name__ == '__main__':
    unittest.main()
