"""Why a Solve stopped reads the same wherever it is shown.

A node's repair loop names the reason it stopped (``stoppedBy``). The failure
sentences and the trace on the server, and the attempts card and the per-node
Solve row in the browser, put that reason into words from one table,
``contracts.SOLVE_STOP_REASONS``, which ``src/generated/solveStopReasons.ts``
copies for the frontend. A node solved on its own runs on its own time budget,
and a node in a Solve session runs on what is left of the session's, so those
are two reasons with two phrases.
"""

from __future__ import annotations

import ast
import itertools
import os
import re
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_verified_rounds as _tvr

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Curio's own Python, and the third-party trees that can sit inside it.
PYTHON_ROOTS = ("utk_curio", "scripts")
NOT_OURS = frozenset({"node_modules", "site-packages", ".venv", "venv", "__pycache__", ".git"})


def _repeated_dict_keys(root: Path) -> list[str]:
    """Every dict literal under *root* that names one constant key twice."""
    found = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = sorted(name for name in subfolders if name not in NOT_OURS)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = Path(folder) / name
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue  # not a module Python can import, so no dict it can build
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                first: dict = {}
                for key in node.keys:
                    if not isinstance(key, ast.Constant):
                        continue
                    if key.value in first:
                        found.append(
                            f"{path.relative_to(REPO_ROOT)}:{key.lineno}: {key.value!r} "
                            f"is already a key on line {first[key.value]}"
                        )
                    else:
                        first[key.value] = key.lineno
    return found


def test_no_dict_literal_in_curio_names_a_key_twice():
    # Python keeps the last value of a repeated key and says nothing, so two
    # meanings can share one key without anyone seeing it.
    found = [line for root in PYTHON_ROOTS for line in _repeated_dict_keys(REPO_ROOT / root)]
    assert found == []


class TestTheStopTable:
    """``contracts.SOLVE_STOP_REASONS``: one entry, and one phrase, per reason."""

    def test_every_reason_has_exactly_one_entry(self):
        from utk_curio.backend.app.agents.domain import contracts

        keys = [reason.key for reason in contracts.SOLVE_STOP_REASONS]
        assert len(keys) == len(set(keys)), keys
        assert contracts.STOPPED_BY_PHRASES == {
            reason.key: reason.phrase for reason in contracts.SOLVE_STOP_REASONS
        }

    def test_a_reason_given_twice_is_refused(self):
        from utk_curio.backend.app.agents.domain import contracts

        twice = (
            contracts.StopReason("budget", "this node's time budget was spent"),
            contracts.StopReason("budget", "this session's time budget was spent"),
        )
        with pytest.raises(ValueError, match="'budget'"):
            contracts.one_phrase_per_reason(twice)

    def test_the_node_and_the_session_budget_are_two_reasons(self):
        from utk_curio.backend.app.agents.domain import contracts

        phrases = contracts.STOPPED_BY_PHRASES
        assert phrases["budget"] == "this node's time budget was spent"
        assert phrases["session"] == "this session's time budget was spent"

    def test_every_phrase_continues_a_sentence_on_one_line(self):
        # A phrase follows "3 attempts · " on the card and sits inside the
        # parentheses of "not fixed after 3 attempts (...)". No en or em dash.
        from utk_curio.backend.app.agents.domain import contracts

        refused = {"\n", "(", ")", chr(0x2013), chr(0x2014)}
        for reason in contracts.SOLVE_STOP_REASONS:
            assert reason.phrase and reason.phrase == reason.phrase.strip(), reason
            assert reason.phrase[0].islower(), reason
            assert not set(reason.phrase) & refused, reason

    def test_the_server_sentences_read_the_table(self):
        from utk_curio.backend.app.agents.application.solve import rounds
        from utk_curio.backend.app.agents.domain import contracts

        assert rounds.STOPPED_BY_PHRASES is contracts.STOPPED_BY_PHRASES
        for reason in contracts.SOLVE_STOP_REASONS:
            expected = "" if reason.key == "passed" else f" ({reason.phrase})"
            assert rounds._stopped_by_clause(reason.key) == expected, reason.key
        assert rounds._stopped_by_clause(None) == ""
        assert rounds._stopped_by_clause("nonsense") == ""


def _loops_find_their_budget_spent(monkeypatch) -> list:
    """Every repair loop Solve starts runs one round and then finds its time
    budget spent, whatever the runner's speed: its clock reads 0 when the loop
    starts and far past any budget before the next round. Returns the budgets
    the loops were handed."""
    from utk_curio.backend.app.agents.application.solve import rounds

    loop = rounds._verified_content_rounds
    handed: list = []

    def _past_its_budget(*args, **kwargs):
        handed.append(kwargs.get("node_budget_s"))
        ticks = itertools.chain([0.0], itertools.repeat(1e9))
        return loop(*args, **{**kwargs, "clock": lambda: next(ticks)})

    monkeypatch.setattr(rounds, "_verified_content_rounds", _past_its_budget)
    return handed


def _session_turns(client, token, ctx) -> list:
    return client.get(
        f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
        headers=_auth(token),
    ).get_json()["turns"]


def _trails(turns, node_id) -> list:
    return [
        part for turn in turns for part in (turn.get("content") or [])
        if part.get("type") == "solveAttempts" and part.get("nodeId") == node_id
    ]


class TestANodeSolvedOnItsOwn:
    """**Solve this node**: the loop runs on the node's own time budget, and
    that is the reason its sentence, its card and its row give."""

    def test_running_out_of_time_names_the_nodes_budget(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _tvr.TestSolveNode()
        bad = h.LOADER.replace("return df", "always_bad()\nreturn df")
        ctx = h._setup(
            client, user, token, monkeypatch, content=bad,
            child_replies=[bad.replace("always_bad()", "always_bad(2)")],
            exec_outcomes={"always_bad": "Traceback: NameError: always_bad"},
        )
        handed = _loops_find_their_budget_spent(monkeypatch)
        done = h._solve_node(client, token, ctx)[-1][1]
        assert handed == [None], "a node solved on its own runs on its own budget"
        turns = _session_turns(client, token, ctx)
        assert turns[-1]["text"].startswith(
            "Not fixed after 1 attempt (this node's time budget was spent): "
        ), turns[-1]["text"]
        # The row under the Solve button names it from the done payload.
        assert done.get("stoppedBy") == "budget", done
        assert [p["stoppedBy"] for p in _trails(turns, "n1")] == ["budget"]

    def test_a_valid_document_names_its_kind_not_the_attempt_cap(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        # The sandbox does not run a Vega-Lite document: the loop checks it
        # once and stops, which is not the attempt cap running out.
        user, token = user_and_token
        h = _tvr.TestSolveNode()
        ctx = h._setup(client, user, token, monkeypatch, content='{"mark": "bar"}', node_type=_tvr.VEGA)
        done = h._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "not-executable" and done["rounds"] == 1
        trails = _trails(_session_turns(client, token, ctx), "n1")
        assert [p["stoppedBy"] for p in trails] == ["not-executable"]
        assert done.get("stoppedBy") == "not-executable", done


class TestANodeInASolveSession:
    """The Dataflow Builder's **Solve**: a node runs on what is left of the
    session's time budget, so running out of it is the session's stop, in
    the node's sentence and on its card alike."""

    def test_running_out_of_time_names_the_sessions_budget(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _tvr.TestVerifiedSolve()
        ctx = h._setup(
            client, user, token, monkeypatch, with_stats=False,
            dl_replies=[h.LOADER.replace("return df", f"always_bad({i})\nreturn df") for i in range(3)],
            exec_outcomes={"always_bad": "Traceback: NameError: always_bad"},
        )
        handed = _loops_find_their_budget_spent(monkeypatch)
        body = h._solve(client, token, ctx)
        assert handed and all(isinstance(s, int) and s >= 1 for s in handed), handed
        load = body["results"][ctx["load"]]
        assert load["status"] == "failed", load
        assert load["stoppedBy"] == "session", load
        assert re.match(
            r"not fixed after \d+ attempts? \(this session's time budget was spent\): ", load["error"]
        ), load["error"]
        trails = _trails(_session_turns(client, token, ctx), ctx["load"])
        assert trails and {p["stoppedBy"] for p in trails} == {"session"}, trails
