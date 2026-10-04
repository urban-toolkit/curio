"""Worked examples: which shipped dataflows a run gets, and where they land.

``turns/examples.py`` picks the "Used" dataflows of ``llm-prompts/examples.md``
closest to what a run knows and renders them as one runtime block, bounded in
size. These tests pin the choice for fixed questions, the bound, the
exclusion, the missing-folder case, the agents that opt in, and that the block
reaches an attached run's system turn and a delegated run's.
"""

from __future__ import annotations

import json
import logging

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.turns import examples
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

# Imported for its helpers. conftest.py runs each class only in the file that
# defines it, never again here.
from utk_curio.backend.tests.test_agents.test_routes_proposals import TestDataflowPlanMint

MILAN = "Milan heat and thermal comfort"
IMAGES = "How do I show images in a table?"
NINE = "09-heterogeneous-data-linked-views"
SIXTEEN = "16-simple-view-tables-and-images"
LAYOUT = {"x", "y", "width", "height", "dashboardX", "dashboardY", "dashboardWidth", "dashboardHeight"}


def _keys(chosen) -> list[str]:
    return [example.key for example in chosen]


def _pool() -> dict:
    return {example.key: example for example in examples.used_examples()}


class TestTheChoice:
    def test_a_milan_heat_and_thermal_comfort_question_picks_example_09(self):
        assert _keys(examples.select(MILAN))[:1] == [NINE]

    def test_a_question_about_images_in_a_table_picks_example_16(self):
        assert _keys(examples.select(IMAGES))[:1] == [SIXTEEN]

    def test_an_empty_query_picks_nothing(self):
        assert examples.select("") == []
        assert examples.select("  ") == []
        assert examples.block_for("") is None

    def test_at_most_two_are_picked(self):
        chosen = examples.select("a map and a bar chart of points per zip code over time")
        assert 0 < len(chosen) <= examples.TOP_K == 2

    def test_the_choice_is_the_same_every_time(self):
        assert _keys(examples.select(IMAGES)) == _keys(examples.select(IMAGES))

    def test_the_bonuses_rank_but_never_choose_alone(self):
        # No shared word, so neither the node's type nor a shared dataset
        # brings an example in.
        assert examples.select("zzzz", dataset_ids={"data.utk.chicago-boundary"}) == []
        # Among examples that share a word, the node's template type ranks first.
        for node_type in ("curio.builtin/autk-grammar", "curio.builtin/vis-vega"):
            top = examples.select("a map", node_type=node_type)[0]
            assert node_type in top.node_types, node_type

    def test_a_dataset_the_dataflow_uses_ranks_its_examples_first(self):
        boundary = "data.utk.chicago-boundary"
        assert boundary not in examples.select("bar chart")[0].dataset_ids
        chosen = examples.select("bar chart", dataset_ids={boundary})
        assert chosen and boundary in chosen[0].dataset_ids


class TestTheBlock:
    def test_the_size_cap_holds(self):
        pool = list(_pool().values())
        block = examples.render(pool)
        assert block is not None and len(block) <= examples.MAX_BLOCK_CHARS
        for query in (MILAN, IMAGES, "bar chart of green roofs per zip code",
                      "a map of buildings coloured by height", "sensor readings over time"):
            block = examples.block_for(query)
            assert block is None or len(block) <= examples.MAX_BLOCK_CHARS, query

    def test_the_milan_question_shows_example_09(self):
        block = examples.block_for(MILAN)
        assert block is not None
        assert _pool()["09-heterogeneous-data-linked-views"].entry.line in block

    def test_an_example_past_the_cap_is_left_out_and_the_next_one_still_fits(self):
        pool = list(_pool().values())
        too_big = [e for e in pool if examples.render([e]) is None]
        fits = [e for e in pool if examples.render([e]) is not None]
        assert too_big and len(fits) >= 2, "the pool no longer has both kinds; this test would be vacuous"
        block = examples.render([too_big[0], fits[0]])
        assert fits[0].entry.line in block and too_big[0].entry.line not in block
        # The ones that fit keep their rank order.
        smallest, next_smallest = sorted(fits, key=lambda e: len(examples.render([e])))[:2]
        pair = examples.render([next_smallest, smallest])
        assert pair.index(next_smallest.entry.line) < pair.index(smallest.entry.line)

    def test_the_block_is_the_heading_then_each_line_and_its_trill(self):
        sixteen = _pool()[SIXTEEN]
        block = examples.render([sixteen])
        assert block.startswith(examples.HEADING)
        assert f"{sixteen.entry.line}\n```json\n" in block
        # The line is shown without its link.
        assert "](" not in block.split("```json")[0]

    def test_the_trill_shown_is_valid_json_without_layout(self):
        for example in _pool().values():
            shown = json.loads(examples.trill_text(example.spec))["dataflow"]
            assert "categories" not in shown and "datasets" not in shown, example.key
            assert len(shown["nodes"]) == len(example.spec["dataflow"]["nodes"]), example.key
            assert len(shown["edges"]) == len(example.spec["dataflow"]["edges"]), example.key
            for node in shown["nodes"]:
                assert not LAYOUT & set(node), (example.key, node.get("id"))
                assert node["id"] and node["type"]

    def test_exclude_leaves_an_example_out(self):
        assert NINE in _keys(examples.select(MILAN))
        for name in (NINE, f"{NINE}.json", f"docs/examples/{NINE}.json"):
            assert NINE not in _keys(examples.select(MILAN, exclude={name})), name
        # A test dataflow by its shipped key or its stem.
        query = "lane histogram of roads"
        assert "dataflows/Regression" in _keys(examples.select(query))
        for name in ("dataflows/Regression", "Regression"):
            assert "dataflows/Regression" not in _keys(examples.select(query, exclude={name})), name


class TestAnEvaluationNeverSeesItsExample:
    """An evaluation marks the project it builds (``dataflow.evaluation``); the
    marker's fixture id keeps the example under test out of every run there."""

    PLAIN = {"dataflow": {"nodes": [], "edges": []}}

    def _marked(self, fixture_id: str) -> dict:
        from utk_curio.backend.app.agents.evaluation import authorization

        return authorization.mark_spec(self.PLAIN, authorization.new_marker("run-1", fixture_id))

    def test_the_marker_names_the_example_to_leave_out(self):
        excluded = examples.excluded_by(self._marked(NINE))
        assert NINE in excluded
        assert examples.excluded_by(self.PLAIN) == set()
        assert NINE not in _keys(examples.select(MILAN, exclude=excluded))

    def test_an_evaluation_is_shown_no_part_of_its_answer(self):
        # Exactly the examples that share a node or edge id, or a code line of
        # SHARED_LINE_CHARS or more, with the scored dataflow are left out.
        answer = examples._answer_parts(_pool()[NINE].spec)
        assert answer, "example 09 has no answer parts; this test would be vacuous"
        excluded = examples.excluded_by(self._marked(NINE))
        for example in _pool().values():
            shares = bool(examples._answer_parts(example.spec) & answer)
            assert (example.key in excluded) == shares, example.key
        block = examples.block_for(MILAN, exclude=excluded) or ""
        assert not [part for part in answer if part in block]

    def test_every_fixture_id_names_its_example(self):
        from utk_curio.backend.app.agents.evaluation.fixtures import load_fixtures

        pool = list(_pool().values())
        named = 0
        for fixture in load_fixtures(validate=False):
            source = fixture.source_path.resolve()
            matches = [e for e in pool if e.is_named_by(fixture.fixture_id)]
            if source in {e.entry.path for e in pool}:
                assert [e.entry.path for e in matches] == [source], fixture.fixture_id
                named += 1
            else:
                assert matches == [], fixture.fixture_id
        assert named, "no fixture is tied to a Used example; this test would be vacuous"

    def test_attached_and_delegated_runs_in_an_evaluation_project_leave_it_out(self):
        line = _pool()[SIXTEEN].entry.line
        marked = self._marked(SIXTEEN)
        dfb = "agent.dataflow-builder@1.0.0"
        assert line in examples.attached_block(dfb, self.PLAIN, {"kind": "canvas"}, IMAGES)
        assert line not in (examples.attached_block(dfb, marked, {"kind": "canvas"}, IMAGES) or "")
        ncb, capability = "agent.node-content-builder@1.0.0", "node.content.generate"
        assert line in examples.delegated_block(ncb, capability, self.PLAIN, {"subtask": IMAGES})
        assert line not in (examples.delegated_block(ncb, capability, marked, {"subtask": IMAGES}) or "")

    def test_the_live_tool_marks_the_project_it_creates(self):
        from utk_curio.backend.app.agents.evaluation import authorization
        from utk_curio.backend.app.agents.evaluation import live as live_mod
        from utk_curio.backend.app.agents.evaluation.fixtures import load_fixtures

        posted = []

        class _Client(live_mod.HttpClient):
            def json(self, path, *, method="GET", payload=None):
                posted.append((path, method, payload))
                return {"id": "p1"}

        run = live_mod.LiveRun(
            client=_Client(base_url="http://x", token="t"), templates={},
            report=live_mod.RunReport(run_id="r-1"),
        )
        fixture = next(f for f in load_fixtures(validate=False) if f.fixture_id == SIXTEEN)
        assert run._create_project(fixture) == "p1"
        ((path, method, payload),) = posted
        assert (path, method) == ("/api/projects", "POST")
        marker = authorization.marker_of(payload["spec"])
        assert (marker.run_id, marker.fixture_id) == ("r-1", SIXTEEN)
        assert examples.excluded_by(payload["spec"]) == {SIXTEEN}


class TestWithoutTheExamplesFolder:
    def test_there_is_no_block_and_one_warning(self, monkeypatch, tmp_path, caplog):
        # A pip install ships no docs/examples.
        from utk_curio.backend.app.projects import shipped

        monkeypatch.setattr(shipped, "examples_dir", lambda: tmp_path / "missing")
        monkeypatch.setattr(examples, "_warned_missing", False)
        with caplog.at_level(logging.WARNING, logger=examples.log.name):
            assert examples.block_for(MILAN) is None
            assert examples.block_for(IMAGES) is None
        warnings = [r for r in caplog.records if "no worked examples" in r.getMessage()]
        assert len(warnings) == 1


class TestWhoTakesThem:
    def test_the_builders_and_workflow_suggest_take_them_and_no_one_else(self):
        taking = set()
        for spec in builtin.BUILTIN_AGENTS:
            coord = f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"
            if builtin.gets_worked_examples(coord):
                taking.add((spec.agent_id, None))
            for mode in spec.modes:
                if builtin.gets_worked_examples(coord, mode.capability):
                    taking.add((spec.agent_id, mode.capability))
        assert taking == {
            ("agent.dataflow-builder", None),
            ("agent.node-builder", None),
            ("agent.node-content-builder", None),
            ("agent.connection-builder", None),
            ("agent.dataflow-reader", "workflow.suggest"),
        }
        # The Node Content Builder's Autark variant is the same agent.
        ncb = "agent.node-content-builder@1.0.0"
        assert builtin.gets_worked_examples(ncb, "node.content.generate")
        assert not builtin.gets_worked_examples("agent.someone-else@1.0.0")

    def test_the_manifests_do_not_change(self):
        for spec in builtin.BUILTIN_AGENTS:
            assert "worked" not in json.dumps(builtin.build_builtin_manifest(spec)), spec.agent_id


class TestTheBlockReachesRuns:
    def test_an_attached_run_carries_it_in_its_runtime_slot(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(client, user, token, alice_project, monkeypatch, replies=["noted"])
        r = helper._run(client, token, alice_project, att_id, message=IMAGES)
        assert r.status_code == 200, r.get_data(as_text=True)
        system = calls[0][0]
        runtime = [s["text"] for s in system["slots"] if s["kind"] == "runtime"]
        block = next((text for text in runtime if text.startswith(examples.HEADING)), None)
        assert block is not None, [text[:60] for text in runtime]
        assert "Simple View: tables and images: " in block
        assert block in system["content"]
        # The cached preamble stays fixed: the block is never in it.
        assert system["slots"][0]["kind"] == "preamble"
        assert examples.HEADING not in system["slots"][0]["text"]

    def test_an_agent_that_does_not_take_them_gets_none(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        helper = TestDataflowPlanMint()
        user, token = user_and_token
        att_id, calls = helper._setup(
            client, user, token, alice_project, monkeypatch,
            replies=["chatting"], coord="agent.chat-agent@1.0.0",
        )
        helper._run(client, token, alice_project, att_id, message=IMAGES)
        assert examples.HEADING not in calls[0][0]["content"]

    def _delegate(self, client, token, user, monkeypatch, coord, capability, inputs) -> dict:
        from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig

        pid = client.post("/api/projects", json={
            "name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
        }, headers=_auth(token)).get_json()["id"]
        calls = []

        def _fake_run(config, messages, **kwargs):
            calls.append(messages)
            return "{}"

        monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _fake_run)
        status, _text, _record = delegation.run_delegate(
            _user_dir_key(user), pid, coord, capability, inputs,
            ProviderConfig(api_key="k", api_type="openai_compatible", base_url="http://x", model="m"),
            parent_execution_id="parent", parent_coord="agent.dataflow-builder@1.0.0", attachment_id=None,
        )
        assert status == "ok"
        (messages,) = calls
        return messages[0]

    def test_a_delegated_run_carries_it_after_its_configuration(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        system = self._delegate(client, token, user, monkeypatch, "agent.node-content-builder@1.0.0",
                                "node.content.generate", {"subtask": IMAGES})
        kinds = [slot["kind"] for slot in system["slots"]]
        assert kinds[-1] == "runtime" and "tool-protocol" not in kinds
        assert system["slots"][-1]["text"].startswith(examples.HEADING)
        assert "Simple View: tables and images: " in system["content"]

    def test_a_delegated_mode_takes_them_only_when_it_opts_in(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        reader = "agent.dataflow-reader@1.0.0"
        suggest = self._delegate(client, token, user, monkeypatch, reader, "workflow.suggest",
                                 {"workflowGoal": IMAGES})
        explain = self._delegate(client, token, user, monkeypatch, reader, "dataflow.explain",
                                 {"workflowGoal": IMAGES})
        assert examples.HEADING in suggest["content"]
        assert examples.HEADING not in explain["content"]
        assert "runtime" not in [slot["kind"] for slot in explain["slots"]]
