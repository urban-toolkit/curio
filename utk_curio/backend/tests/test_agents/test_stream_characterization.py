"""Characterization tests for the six agent streams (memo dev/142, B3).

These pin the EVENT SEQUENCE each stream emits for one scripted scenario —
event names in order, plus the stable fields of the terminal payload — as
observed before the loops behind them were decomposed. They exist so B3 can
move code without moving behavior: a decomposition that changes what a
stream says, or the order it says it in, fails here before any product
test has to notice. They deliberately reuse the scenario helpers of the
product tests (``test_verified_rounds``, ``test_routes_*``) rather than build
new fixtures, so the scenarios are the ones those tests already trust.

To re-record after an INTENDED behavior change, run with
``CURIO_CHARACTERIZE=1`` and paste the printed sequences below.
"""

from __future__ import annotations

import json
import os

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
from utk_curio.backend.tests.test_agents import test_verified_rounds as _tvr

RECORD = os.environ.get("CURIO_CHARACTERIZE") == "1"


def _check(name: str, actual: dict, expected: dict | None) -> None:
    if RECORD or expected is None:
        print(f"\n[characterize] {name} = {json.dumps(actual, sort_keys=True)}")
    if expected is not None:
        assert actual == expected, f"{name} diverged; actual = {json.dumps(actual, sort_keys=True)}"


def _names(events) -> list[str]:
    return [k for k, _ in events]


# ── goldens (recorded 2026-09-29 on enh/agent-catalog at 62ed60b4, before B3 was re-derived here) ──
# solve_batch_two_waves' "passes" edited by hand from 2 to 1 for issue #583: the
# session makes one pass there, and the payload used to count the turn that
# found nothing left as a second one.

GOLDEN: dict[str, dict | None] = {'run_node_chain': {'doneKeys': ['blocker',
                                 'error',
                                 'executionId',
                                 'nodeId',
                                 'nodes',
                                 'ok',
                                 'order'],
                    'names': ['run_started', 'node_executed', 'node_executed', 'done'],
                    'ok': True,
                    'order_len': 2,
                    'outputTypes': ['dataframe', 'dataframe']},
 'simulate_auto': {'doneKeys': ['builderSession', 'mode', 'status'],
                   'edgeStates': {'0': 'applied'},
                   'names': ['simulate_started',
                             'stage',
                             'node_created',
                             'action_result',
                             'stage',
                             'validation_started',
                             'generation_round',
                             'node_executed',
                             'round_verdict',
                             'action_result',
                             'stage',
                             'node_content_applied',
                             'action_result',
                             'stage',
                             'node_created',
                             'edges_created',
                             'action_result',
                             'stage',
                             'validation_started',
                             'generation_round',
                             'node_executed',
                             'node_executed',
                             'round_verdict',
                             'action_result',
                             'stage',
                             'node_content_applied',
                             'action_result',
                             'done'],
                   'nodeStates': ['approved', 'approved'],
                   'status': 'completed'},
 'solve_batch_two_waves': {'appliedContents': ['load', 'stats'],
                           'cancelled': False,
                           'doneKeys': ['appliedContents',
                                        'attachmentId',
                                        'builderSession',
                                        'cancelled',
                                        'endedBy',
                                        'executionId',
                                        'mode',
                                        'notAttempted',
                                        'passes',
                                        'results',
                                        'waiting'],
                           'endedBy': 'complete',
                           'names': ['solve_started',
                                     'solve_pass',
                                     'solve_wave',
                                     'node_started',
                                     'node_round',
                                     'node_executed',
                                     'node_verdict',
                                     'node_result',
                                     'solve_wave',
                                     'node_started',
                                     'node_round',
                                     'node_executed',
                                     'node_executed',
                                     'node_verdict',
                                     'node_round',
                                     'node_executed',
                                     'node_executed',
                                     'node_verdict',
                                     'node_result',
                                     'done'],
                           'passes': 1,
                           'results': {'load': {'attempts': ['pass'],
                                                'rounds': 1,
                                                'status': 'solved',
                                                'verdict': 'pass'},
                                       'stats': {'attempts': ['fail', 'pass'],
                                                 'rounds': 2,
                                                 'status': 'solved',
                                                 'verdict': 'pass'}},
                           'waves': [[1, 2, 1], [2, 2, 1]]},
 'solve_node_fix': {'attempts': [['fail', 'current content'], ['pass', 'generated']],
                    'doneKeys': ['attempts',
                                 'evidence',
                                 'nodeId',
                                 'proposalAttachmentId',
                                 'proposalId',
                                 'rounds',
                                 'verdict'],
                    'names': ['solve_node_started',
                              'generation_round',
                              'node_executed',
                              'round_verdict',
                              'generation_round',
                              'node_executed',
                              'round_verdict',
                              'done'],
                    'rounds': 2,
                    'spec_content_replaced': False,
                    'verdict': 'pass'},
 'turn_stream_deltas': {'content': [],
                        'doneKeys': ['content', 'durationMs', 'executionId', 'reply', 'usage'],
                        'names': ['execution', 'delta', 'delta', 'done'],
                        'reply': 'hello',
                        'turns': [['user', 'q1'], ['agent', 'hello']]},
 'validate_node_pass': {'doneKeys': ['attempts',
                                     'builderSession',
                                     'evidence',
                                     'nodeId',
                                     'proposalAttachmentId',
                                     'proposalId',
                                     'rounds',
                                     'verdict'],
                        'names': ['validation_started',
                                  'generation_round',
                                  'node_executed',
                                  'round_verdict',
                                  'done'],
                        'nodeState': 'validated',
                        'outputDataType': 'dataframe',
                        'rounds': 1,
                        'verdict': 'pass'}}


class TestSolveBatchStream:
    @pytest.mark.parametrize("sandbox_run_s", [0, 1.2], ids=["idle", "loaded"])
    def test_two_waves_loader_passes_stats_fails_then_passes(
        self, client, user_and_token, tmp_curio, monkeypatch, sandbox_run_s
    ):
        user, token = user_and_token
        h = _tvr.TestVerifiedSolve()
        ctx = h._setup(
            client, user, token, monkeypatch, dl_replies=[h.LOADER],
            ca_replies=["bad_stats(arg[0])\nreturn 1", "df = arg[0]\nreturn df.describe()"],
            exec_outcomes={"bad_stats": "Traceback: NameError: bad_stats"},
        )
        # The stats node passes in its second round. A sandbox run of 1.2 s
        # outlasts a one-second repair budget on its own. The stream is the
        # same whatever the runner's speed.
        h._on_a_loaded_runner(monkeypatch, sandbox_run_s)
        events = h._stream(client, token, ctx)
        done = events[-1][1]
        by_node = {k: v for k, v in done["results"].items()}
        actual = {
            "names": _names(events),
            "waves": [[p["wave"], p["of"], len(p["nodeIds"])] for k, p in events if k == "solve_wave"],
            "results": {("load" if nid == ctx["load"] else "stats"): {
                "status": r["status"], "verdict": r.get("verdict"), "rounds": r.get("rounds"),
                "attempts": [a.get("verdict") for a in (r.get("attempts") or [])],
            } for nid, r in by_node.items()},
            "endedBy": done["endedBy"], "passes": done["passes"], "cancelled": done["cancelled"],
            "doneKeys": sorted(done.keys()),
            "appliedContents": sorted("load" if i["nodeId"] == ctx["load"] else "stats" for i in done["appliedContents"]),
        }
        _check("solve_batch_two_waves", actual, GOLDEN["solve_batch_two_waves"])


class TestSolveNodeStream:
    def test_failing_content_is_fixed(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        h = _tvr.TestSolveNode()
        bad = 'import pandas as pd\ndataset_path = curio_data_path("{DATASET}")\ndf = pd.read_csv(dataset_path, sep="|||")\nbad_sep()\nreturn df'
        ctx = h._setup(client, user, token, monkeypatch, content=bad, child_replies=[h.LOADER],
                       exec_outcomes={"bad_sep": "Traceback: ParserError: bad separator"})
        events = h._solve_node(client, token, ctx)
        done = events[-1][1]
        actual = {
            "names": _names(events),
            "verdict": done["verdict"], "rounds": done["rounds"],
            "attempts": [[a.get("verdict"), a.get("source")] for a in done["attempts"]],
            "doneKeys": sorted(done.keys()),
            "spec_content_replaced": "bad_sep" not in h._content(ctx),
        }
        _check("solve_node_fix", actual, GOLDEN["solve_node_fix"])


class TestSimulationStream:
    def test_auto_mode(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        h = routes_solve.TestSimulationDriver()
        plan = routes_proposals.TestDataflowPlanMint()
        h._fake_exec(monkeypatch)
        att_id, proposal, _ = h._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + plan._plan_tail(), "print('generated')"],
        )
        events = h._simulate(client, token, alice_project, att_id, "auto")
        done = events[-1][1]
        actual = {
            "names": _names(events),
            "status": done["status"],
            "nodeStates": sorted(done["builderSession"]["nodeStates"].values()),
            "edgeStates": done["builderSession"]["edgeStates"],
            "doneKeys": sorted(done.keys()),
        }
        _check("simulate_auto", actual, GOLDEN["simulate_auto"])


class TestRunNodeStream:
    def test_chain_runs(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        h = routes_solve.TestProgressiveLifecycle()
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {"stdout": ["ran"], "stderr": "",
                                       "output": {"path": "art-run", "dataType": "dataframe"}},
        )
        att_id, proposal = h._mint(client, user, token, alice_project, monkeypatch)
        pid = proposal["proposalId"]
        refs = [n["ref"] for n in proposal["plan"]["nodes"]]
        h._apply_node(client, token, alice_project, att_id, pid, refs[0])
        h._apply_node(client, token, alice_project, att_id, pid, refs[1])
        r = client.post(f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
                        json={"ref": refs[1]}, headers=_auth(token))
        assert r.status_code == 200
        events = routes_solve.TestStreamedSolve()._sse_events(r)
        done = events[-1][1]
        actual = {
            "names": _names(events), "ok": done["ok"], "order_len": len(done["order"]),
            "doneKeys": sorted(done.keys()),
            "outputTypes": sorted(n["output"]["dataType"] for n in done["nodes"].values()),
        }
        _check("run_node_chain", actual, GOLDEN["run_node_chain"])


class TestValidateNodeStream:
    def test_pass_verdict(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        user, token = user_and_token
        h = routes_solve.TestValidateNode()
        plan = routes_proposals.TestDataflowPlanMint()
        h._fake_exec(monkeypatch)
        att_id, ref, created, _ = h._setup_plan_node(
            client, user, token, alice_project, monkeypatch,
            replies=["Plan.\n" + plan._plan_tail(), "print('validated code')"],
        )
        events = h._validate(client, token, alice_project, att_id, {"ref": ref})
        done = events[-1][1]
        actual = {
            "names": _names(events), "verdict": done["verdict"], "rounds": done["rounds"],
            "outputDataType": done["evidence"]["outputDataType"],
            "nodeState": done["builderSession"]["nodeStates"][ref],
            "doneKeys": sorted(done.keys()),
        }
        _check("validate_node_pass", actual, GOLDEN["validate_node_pass"])


class TestTurnStream:
    def test_deltas_then_done(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        def _fake_stream(config, messages, **kwargs):
            yield "hel"
            yield "lo"

        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn", _fake_stream)
        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn",
                            lambda c, m, **kw: "Stream Title")
        _, token = user_and_token
        h = routes_turns.TestStreamRun()
        att_id = h._attach_builtin(client, token, alice_project)
        r = client.post(f"/api/agents/projects/{alice_project}/attachments/{att_id}/run/stream",
                        json={"message": "q1"}, headers=_auth(token))
        assert r.status_code == 200
        events = h._events(r)
        done = events[-1][1]
        turns = client.get(f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
                           headers=_auth(token)).get_json()["turns"]
        actual = {
            "names": _names(events), "reply": done.get("reply"), "content": done.get("content"),
            "doneKeys": sorted(done.keys()),
            "turns": [[t["role"], t["text"]] for t in turns],
        }
        _check("turn_stream_deltas", actual, GOLDEN.get("turn_stream_deltas"))
