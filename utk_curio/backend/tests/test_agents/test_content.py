"""Tests for the typed content-part contracts + structured-tail parser
(memo dev/39, DEC-043)."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import content


def _tail(payload: object) -> str:
    return f"```curio.v1\n{json.dumps(payload)}\n```"


PROMPTS = {"suggestedPrompts": {"primary": "Do the thing", "alternatives": ["Or this"]}}


class TestSplitTail:
    def test_no_fence_returns_reply_untouched(self):
        assert content.split_tail("plain reply") == ("plain reply", None)

    def test_terminal_block_is_split(self):
        reply = "Here you go.\n\n" + _tail(PROMPTS)
        visible, body = content.split_tail(reply)
        assert visible == "Here you go."
        assert json.loads(body) == PROMPTS

    def test_trailing_whitespace_after_close_is_tolerated(self):
        reply = "Text\n" + _tail(PROMPTS) + "\n  \n"
        visible, body = content.split_tail(reply)
        assert visible == "Text"
        assert body is not None

    def test_mid_reply_block_is_body_text(self):
        reply = "Example:\n" + _tail(PROMPTS) + "\nAnd more prose after."
        assert content.split_tail(reply) == (reply, None)

    def test_reply_that_is_only_a_block(self):
        reply = _tail(PROMPTS)
        visible, body = content.split_tail(reply)
        assert visible == ""
        assert body is not None

    def test_unclosed_fence_is_not_a_tail(self):
        reply = "Text\n```curio.v1\n{\"suggestedPrompts\":"
        assert content.split_tail(reply) == (reply, None)

    def test_fence_not_at_line_start_is_not_a_tail(self):
        reply = "inline ```curio.v1\n{}\n```"
        assert content.split_tail(reply) == (reply, None)

    def test_last_terminal_block_wins_over_earlier_quoted_one(self):
        reply = "Syntax:\n" + _tail({"x": 1}) + "\nUse it like so.\n" + _tail(PROMPTS)
        visible, body = content.split_tail(reply)
        assert visible.endswith("Use it like so.")
        assert json.loads(body) == PROMPTS


class TestParseParts:
    def test_suggested_prompts_parse(self):
        parts = content.parse_parts(json.dumps(PROMPTS))
        assert parts == [
            {"type": "suggestedPrompts", "primary": "Do the thing", "alternatives": ["Or this"]}
        ]

    def test_alternatives_optional_and_deduped(self):
        payload = {
            "suggestedPrompts": {
                "primary": "P",
                "alternatives": ["A", "A", "P"],
            }
        }
        (part,) = content.parse_parts(json.dumps(payload))
        # Duplicates and primary-echoes are dropped, order kept.
        assert part["alternatives"] == ["A"]

    def test_cards_parse_in_order_before_prompts(self):
        payload = {
            "cards": [{"kind": "result", "title": "Created node", "lines": ["a", "b"]}],
            **PROMPTS,
        }
        parts = content.parse_parts(json.dumps(payload))
        assert [p["type"] for p in parts] == ["card", "suggestedPrompts"]
        assert parts[0] == {
            "type": "card",
            "kind": "result",
            "title": "Created node",
            "lines": ["a", "b"],
        }

    def test_card_lines_optional(self):
        payload = {"cards": [{"kind": "result", "title": "T"}]}
        (card,) = content.parse_parts(json.dumps(payload))
        assert card["lines"] == []

    def test_unknown_top_level_keys_are_ignored(self):
        payload = {**PROMPTS, "futurePartType": {"x": 1}}
        parts = content.parse_parts(json.dumps(payload))
        assert [p["type"] for p in parts] == ["suggestedPrompts"]

    def test_unknown_only_payload_is_invalid(self):
        assert content.parse_parts(json.dumps({"futurePartType": {}})) is None

    def test_bad_json_is_invalid(self):
        assert content.parse_parts("{not json") is None

    def test_non_object_payload_is_invalid(self):
        assert content.parse_parts(json.dumps([1, 2])) is None

    def test_bounds_primary_length(self):
        payload = {"suggestedPrompts": {"primary": "x" * 201}}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_bounds_alternative_count(self):
        payload = {"suggestedPrompts": {"primary": "P", "alternatives": ["a", "b", "c", "d"]}}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_bounds_empty_primary(self):
        payload = {"suggestedPrompts": {"primary": "   "}}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_bounds_card_count_and_fields(self):
        card = {"kind": "result", "title": "T"}
        assert content.parse_parts(json.dumps({"cards": [card] * 5})) is None
        assert content.parse_parts(json.dumps({"cards": [{"kind": "", "title": "T"}]})) is None
        assert (
            content.parse_parts(json.dumps({"cards": [{"kind": "k", "title": "x" * 121}]}))
            is None
        )
        assert (
            content.parse_parts(
                json.dumps({"cards": [{"kind": "k", "title": "T", "lines": ["y" * 301]}]})
            )
            is None
        )

    def test_bounds_block_size(self):
        payload = {"suggestedPrompts": {"primary": "P"}, "pad": "x" * 5000}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_one_malformed_known_part_invalidates_the_block(self):
        # Fail-open to text beats attaching half-validated content.
        payload = {
            "cards": [{"kind": "result", "title": "ok"}, {"kind": "bad"}],  # second lacks title
        }
        assert content.parse_parts(json.dumps(payload)) is None


class TestToolRequestPart:
    """toolRequest parsing (memo dev/41): one per reply, exclusive, bounded."""

    def test_valid_tool_request_parses(self):
        parts = content.parse_parts(
            json.dumps({"toolRequest": {"tool": "dataflow.read", "params": {}}})
        )
        assert parts == [{"type": "toolRequest", "tool": "dataflow.read", "params": {}}]

    def test_params_default_to_empty_object(self):
        (part,) = content.parse_parts(json.dumps({"toolRequest": {"tool": "node.read"}}))
        assert part["params"] == {}

    def test_tool_id_grammar_enforced(self):
        for bad in ("Read", "dataflow", "dataflow/read", "dataflow_read"):
            assert content.parse_parts(json.dumps({"toolRequest": {"tool": bad}})) is None

    def test_params_size_bounded(self):
        payload = {"toolRequest": {"tool": "node.read", "params": {"x": "y" * 2000}}}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_request_is_exclusive_other_parts_dropped(self):
        # A request turn is a request turn (dev/41 §4.1).
        payload = {
            "toolRequest": {"tool": "dataflow.read", "params": {}},
            **PROMPTS,
        }
        parts = content.parse_parts(json.dumps(payload))
        assert [p["type"] for p in parts] == ["toolRequest"]

    def test_malformed_request_invalidates_the_block(self):
        payload = {"toolRequest": {"params": {}}, **PROMPTS}  # missing tool id
        assert content.parse_parts(json.dumps(payload)) is None

    def test_model_emitted_proposal_invalidates_the_block(self):
        # The review flow can never be spoofed from the tail (dev/41 §4.1).
        for key in ("proposal", "proposals"):
            payload = {key: {"tool": "node.content.write"}, **PROMPTS}
            assert content.parse_parts(json.dumps(payload)) is None


class TestContentClassToolBudgets:
    """#245 — the mutate tools whose params carry a node's SOURCE.

    The parser refused at 1KB (``_TOOL_PARAMS_MAX_BYTES``) what the mints
    accept at ``PROPOSAL_CONTENT_MAX_CHARS`` (65536), so every non-trivial
    node.create failed open and the whole request rendered as raw JSON in the
    chat with no node and no review card. The budget is scoped to the CONTENT
    FIELD, never to the tool — the smuggling tests below are why.
    """

    def _request(self, tool, params):
        return json.dumps({"toolRequest": {"tool": tool, "params": params}})

    def test_node_create_content_gets_the_proposal_budget(self):
        body = self._request("node.create", {
            "nodeType": "curio.builtin/computation-analysis",
            "content": "x" * 20000, "title": "Loader", "goal": "load a CSV"})
        assert len(body.encode()) > content.TAIL_MAX_BYTES
        (part,) = content.parse_parts(body)
        assert part["tool"] == "node.create"
        assert len(part["params"]["content"]) == 20000  # byte-identical passthrough

    def test_content_over_the_mint_bound_is_refused(self):
        # Parser and mint now agree at ONE number, so an oversized body is a
        # correctable refusal rather than a silent fail-open leak.
        body = self._request("node.create", {
            "nodeType": "a/b", "content": "x" * (content.PROPOSAL_CONTENT_MAX_CHARS + 1)})
        assert content.parse_parts(body) is None

    def test_non_content_params_keep_a_classic_cap(self):
        # The whole reason the budget is field-scoped: a per-tool budget would
        # hand `pad` a 256KB allowance too.
        body = self._request("node.create", {"pad": "x" * 8000})
        assert content.parse_parts(body) is None

    def test_node_content_write_gets_it_too(self):
        (part,) = content.parse_parts(
            self._request("node.content.write", {"nodeId": "n1", "content": "z" * 20000}))
        assert part["tool"] == "node.content.write"

    def test_node_template_create_nests_its_content(self):
        # The fallback rung of the reuse ladder carries its source one level
        # down, at params.template.content (services.py::_mint_node_template_create).
        (part,) = content.parse_parts(self._request("node.template.create", {
            "justification": "j" * 2000,
            "template": {"label": "L", "engine": "python", "content": "y" * 20000}}))
        assert len(part["params"]["template"]["content"]) == 20000
        assert content.parse_parts(self._request("node.template.create", {
            "template": {"content": "y" * (content.PROPOSAL_CONTENT_MAX_CHARS + 1)}})) is None
        # The justification is prose for the review card, not a code channel.
        assert content.parse_parts(self._request("node.template.create", {
            "justification": "j" * 6000, "template": {"content": "y"}})) is None

    def test_wrong_typed_content_still_reaches_the_mint(self):
        # A non-str content field is left in the remainder so the mint's own
        # "must be a non-empty string" refusal fires — behaviour unchanged.
        assert content.parse_parts(self._request("node.create", {
            "nodeType": "a/b", "content": {"not": "a string"}})) is not None

    def test_other_tools_are_byte_identical(self):
        assert content.parse_parts(self._request("node.read", {"x": "y" * 2000})) is None
        (part,) = content.parse_parts(self._request("node.create", {
            "nodeType": "a/b", "content": "print(1)"}))
        assert part["params"]["content"] == "print(1)"

    def test_smuggling_a_content_tool_name_stays_refused(self):
        payload = {"suggestedPrompts": {"primary": "P"},
                   "pad": '"node.create"' + "x" * 8000}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_verbose_errors_name_the_real_field_path(self):
        _, errors = content.parse_tool_request_verbose({
            "tool": "node.template.create",
            "params": {"template": {"content": "y" * (content.PROPOSAL_CONTENT_MAX_CHARS + 1)}}})
        # The model cannot correct what the error does not name.
        assert errors and "params.template.content" in errors[0]
        _, errors = content.parse_tool_request_verbose({"tool": "node.create", "params": []})
        assert errors == ["toolRequest.params must be an object"]

    def test_the_reported_leak_is_gone_end_to_end(self):
        # Issue #245's exact shape: prose, then the request block.
        body = self._request("node.create", {
            "nodeType": "curio.builtin/computation-analysis", "content": "x" * 20000})
        visible, parts = content.extract_content("I will add that node.\n\n"
                                                 f"```curio.v1\n{body}\n```")
        assert parts and parts[0]["tool"] == "node.create"
        assert "toolRequest" not in visible


class TestTailInstruction:
    def test_grantless_instruction_is_byte_identical(self):
        # Regression pin (dev/41): runs without grants are unchanged from T2.
        assert content.tail_instruction() == content.TAIL_INSTRUCTION
        assert content.tail_instruction([]) == content.TAIL_INSTRUCTION

    def test_granted_instruction_enumerates_exactly_the_grants(self):
        text = content.tail_instruction(
            [("dataflow.read", "Read the saved spec."), ("node.read", "Read one node.")]
        )
        assert text.startswith(content.TAIL_INSTRUCTION)
        assert "- dataflow.read: Read the saved spec." in text
        assert "- node.read: Read one node." in text
        assert '"toolRequest"' in text


class TestProposalPart:
    def test_builder_shape_and_summary_bound(self):
        part = content.make_proposal_part(
            proposal_id="p1",
            tool="node.content.write",
            summary="x" * 300,
            preview="new content",
            pins={"nodeId": "n1", "contentSha256": "abc"},
        )
        assert part["type"] == "proposal"
        assert part["status"] == "pending"
        assert len(part["summary"]) == 200
        assert part["pins"] == {"nodeId": "n1", "contentSha256": "abc"}

    def test_creation_pins_carry_node_type_only(self):
        # dev/48: node.create pins no digest — the id is server-minted at
        # apply; the template is re-validated there instead.
        part = content.make_proposal_part(
            proposal_id="p2",
            tool="node.create",
            summary="Create a new Computation Analysis node",
            preview="print('hi')",
            pins={"nodeType": "curio.builtin/computation-analysis"},
        )
        assert part["pins"] == {"nodeType": "curio.builtin/computation-analysis"}


class TestExtractContent:
    def test_valid_tail_is_stripped_and_typed(self):
        reply = "Answer.\n" + _tail(PROMPTS)
        visible, parts = content.extract_content(reply)
        assert visible == "Answer."
        assert parts[0]["type"] == "suggestedPrompts"

    def test_invalid_tail_stays_visible_verbatim(self):
        reply = "Answer.\n```curio.v1\n{broken\n```"
        visible, parts = content.extract_content(reply)
        assert visible == reply  # fail-open: nothing stripped, nothing lost
        assert parts == []

    def test_no_tail_passthrough(self):
        assert content.extract_content("plain") == ("plain", [])

    def test_reply_that_is_only_a_valid_block_yields_empty_text(self):
        visible, parts = content.extract_content(_tail(PROMPTS))
        assert visible == ""
        assert len(parts) == 1


class TestDelegateRequestPart:
    """dev/48 §3.4 — the model surface for depth-1 delegation."""

    def test_valid_request_is_exclusive(self):
        body = '{"delegateRequest": {"capability": "node.content.generate", "inputs": {"intent": "x"}}, "suggestedPrompts": {"primary": "next"}}'
        parts = content.parse_parts(body)
        assert parts == [
            {
                "type": "delegateRequest",
                "capability": "node.content.generate",
                "inputs": {"intent": "x"},
            }
        ]

    def test_capability_grammar_enforced(self):
        for bad in ("NotACap", "cap", "a..b", "a.b/c", ""):
            body = f'{{"delegateRequest": {{"capability": "{bad}", "inputs": {{}}}}}}'
            assert content.parse_parts(body) is None

    def test_inputs_must_be_bounded_object(self):
        assert content.parse_parts('{"delegateRequest": {"capability": "a.b", "inputs": []}}') is None
        big = "x" * 4000
        assert (
            content.parse_parts(
                f'{{"delegateRequest": {{"capability": "a.b", "inputs": {{"k": "{big}"}}}}}}'
            )
            is None
        )

    def test_both_requests_in_one_tail_invalidates_the_block(self):
        body = (
            '{"toolRequest": {"tool": "dataflow.read", "params": {}}, '
            '"delegateRequest": {"capability": "a.b", "inputs": {}}}'
        )
        assert content.parse_parts(body) is None

    def test_inputs_default_to_empty(self):
        parts = content.parse_parts('{"delegateRequest": {"capability": "a.b"}}')
        assert parts[0]["inputs"] == {}


class TestDelegationInstruction:
    def test_names_entries_and_syntax(self):
        text = content.delegation_instruction(
            [("node.content.generate", "Node Content Builder")]
        )
        assert "- node.content.generate — handled by Node Content Builder" in text
        assert '"delegateRequest"' in text


class TestDatasetCandidatesPart:
    """dev/50 — the docs/06 two-lane suggestions contract: bounded,
    scheme-allowlisted, informational rows; coexists with suggestedPrompts;
    any malformed row fails the whole block open to text."""

    def _row(self, lane="catalog", **over):
        base = {
            "name": "Cities",
            "sourceType": "catalog" if lane == "catalog" else "api",
        }
        if lane == "catalog":
            base["datasetId"] = "imported.abc@1"
        base.update(over)
        return base

    def test_two_lanes_parse_and_coexist_with_prompts(self):
        payload = {
            "datasetCandidates": {
                "lanes": {
                    "external": [
                        {
                            "name": "NOAA Climate Data API",
                            "sourceType": "api",
                            "url": "https://api.noaa.gov",
                            "provider": "NOAA",
                            "format": "json",
                            "fit": {"score": 90, "rationale": "direct match"},
                            "requirement": "API token required",
                        }
                    ],
                    "catalog": [self._row(installed=True)],
                }
            },
            "suggestedPrompts": {"primary": "Install Cities from the catalog"},
        }
        parts = content.parse_parts(json.dumps(payload))
        types = [p["type"] for p in parts]
        assert types == ["datasetCandidates", "suggestedPrompts"]
        lanes = parts[0]["lanes"]
        assert lanes["external"][0]["fit"] == {"score": 90, "rationale": "direct match"}
        assert lanes["catalog"][0]["datasetId"] == "imported.abc@1"
        assert lanes["catalog"][0]["installed"] is True

    def test_catalog_rows_require_dataset_id(self):
        payload = {"datasetCandidates": {"lanes": {"catalog": [
            {"name": "Cities", "sourceType": "catalog"},
        ]}}}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_unsafe_url_schemes_invalidate_the_block(self):
        for url in ("javascript:alert(1)", "data:text/html,x", "ftp://x", "//evil"):
            payload = {"datasetCandidates": {"lanes": {"external": [
                {"name": "X", "sourceType": "api", "url": url},
            ]}}}
            assert content.parse_parts(json.dumps(payload)) is None, url

    def test_row_and_lane_bounds(self):
        too_many = [self._row() for _ in range(9)]
        assert content.parse_parts(json.dumps(
            {"datasetCandidates": {"lanes": {"catalog": too_many}}}
        )) is None
        assert content.parse_parts(json.dumps(
            {"datasetCandidates": {"lanes": {"catalog": [self._row(name="x" * 121)]}}}
        )) is None
        assert content.parse_parts(json.dumps(
            {"datasetCandidates": {"lanes": {"external": [
                {"name": "X", "sourceType": "spaceship"},
            ]}}}
        )) is None
        assert content.parse_parts(json.dumps(
            {"datasetCandidates": {"lanes": {"external": [
                {"name": "X", "sourceType": "api", "fit": {"score": 250, "rationale": "r"}},
            ]}}}
        )) is None

    def test_empty_lanes_are_invalid(self):
        payload = {"datasetCandidates": {"lanes": {"external": [], "catalog": []}}}
        assert content.parse_parts(json.dumps(payload)) is None


class TestDataflowPlanPart:
    """dev/52 — the DR-1 typed plan grammar: backstop bounds (never product
    ceilings), the plan-specific tail budget, plan-local ref integrity."""

    def _plan(self, n_nodes=3, with_edges=True, **over):
        nodes = [
            {"ref": f"n{i}", "nodeType": "curio.builtin/computation-analysis",
             "title": f"Step {i}", "intent": f"does step {i}"}
            for i in range(n_nodes)
        ]
        edges = (
            [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(n_nodes - 1)]
            if with_edges else []
        )
        plan = {"goal": "build the flow", "nodes": nodes, "edges": edges}
        plan.update(over)
        return plan

    def test_valid_plan_parses_alongside_prompts(self):
        payload = {"dataflowPlan": self._plan(), **PROMPTS}
        parts = content.parse_parts(json.dumps(payload))
        assert [p["type"] for p in parts] == ["dataflowPlan", "suggestedPrompts"]
        assert len(parts[0]["nodes"]) == 3
        assert parts[0]["edges"][0] == {"from": "n0", "to": "n1"}

    def test_large_plan_gets_its_own_tail_budget(self):
        # Well past the classic 4096-byte cap — sized-for-real-graphs
        # regression: the app handles far more than a dozen nodes.
        plan = self._plan(n_nodes=150)
        body = json.dumps({"dataflowPlan": plan})
        assert len(body.encode()) > content.TAIL_MAX_BYTES
        parts = content.parse_parts(body)
        assert parts is not None and len(parts[0]["nodes"]) == 150

    def test_large_non_plan_tail_still_fails_the_classic_cap(self):
        payload = {"suggestedPrompts": {"primary": "P"}, "pad": "x" * 8000}
        assert content.parse_parts(json.dumps(payload)) is None
        # And smuggling the KEY STRING inside a value doesn't unlock it.
        payload = {"suggestedPrompts": {"primary": "P"}, "pad": '"dataflowPlan"' + "x" * 8000}
        assert content.parse_parts(json.dumps(payload)) is None

    def test_large_authoring_delegation_gets_the_enlarged_budget(self):
        # dev/90 A6: the live Researcher failure — a node.kind.author
        # delegation whose inputs carry the post-it look spec + findings blew
        # the classic 3KB inputs cap and failed open as visible text. The
        # authoring capabilities now get the plan-class budget.
        inputs = {"look": "post-it", "requirements": "r" * 6000,
                  "findings": ["f" * 2000]}
        body = json.dumps({"delegateRequest": {
            "capability": "node.kind.author", "inputs": inputs}})
        assert len(body.encode()) > content.TAIL_MAX_BYTES
        parts = content.parse_parts(body)
        assert parts is not None and parts[0]["capability"] == "node.kind.author"
        # Ordinary delegations keep the classic cap — content generation
        # inputs are intent + context, never look specs.
        big_ordinary = json.dumps({"delegateRequest": {
            "capability": "node.content.generate",
            "inputs": {"intent": "x" * 6000}}})
        assert content.parse_parts(big_ordinary) is None
        # Smuggling an authoring capability STRING inside another payload
        # does not unlock the budget (the payload-key re-check).
        smuggle = json.dumps({"suggestedPrompts": {"primary": "P"},
                              "pad": '"node.kind.author"' + "x" * 8000})
        assert content.parse_parts(smuggle) is None

    def test_large_package_draft_gets_the_draft_class_budget(self):
        # dev/89: a package draft carries a whole package (manifest + behavior
        # sources) — the same enlarged budget plans get, same payload-key
        # re-check so a non-draft tail can't ride it.
        params = {"mode": "create", "target": "a.b@1",
                  "manifest": {"id": "a.b"}, "files": {"sources/x.tsx": {"text": "y" * 8000}}}
        body = json.dumps({"toolRequest": {"tool": "package.draft.apply", "params": params}})
        assert len(body.encode()) > content.TAIL_MAX_BYTES
        parts = content.parse_parts(body)
        assert parts is not None and parts[0]["tool"] == "package.draft.apply"
        # A different tool smuggling the draft key string stays refused.
        smuggle = json.dumps({"toolRequest": {"tool": "node.create",
                                              "params": {"pad": '"package.draft.apply"' + "x" * 8000}}})
        assert content.parse_parts(smuggle) is None

    def test_backstop_bounds(self):
        assert content.parse_parts(json.dumps({"dataflowPlan": self._plan(n_nodes=201)})) is None
        big_edges = self._plan(n_nodes=3)
        big_edges["edges"] = [{"from": "n0", "to": "n1"}] * 601
        assert content.parse_parts(json.dumps({"dataflowPlan": big_edges})) is None

    def test_ref_integrity(self):
        dup = self._plan(n_nodes=2)
        dup["nodes"][1]["ref"] = "n0"
        assert content.parse_parts(json.dumps({"dataflowPlan": dup})) is None
        # dev/59: an endpoint outside the plan refs names an EXISTING node —
        # grammar-valid; existence is the mint's spec check.
        existing = self._plan(n_nodes=2)
        existing["edges"] = [{"from": "n0", "to": "some-existing-node-id"}]
        parts = content.parse_parts(json.dumps({"dataflowPlan": existing}))
        assert parts is not None
        assert parts[0]["edges"][-1] == {"from": "n0", "to": "some-existing-node-id"}
        self_edge = self._plan(n_nodes=2)
        self_edge["edges"] = [{"from": "n0", "to": "n0"}]
        assert content.parse_parts(json.dumps({"dataflowPlan": self_edge})) is None
        dup_edge = self._plan(n_nodes=2)
        dup_edge["edges"] = [{"from": "n0", "to": "n1"}, {"from": "n0", "to": "n1"}]
        assert content.parse_parts(json.dumps({"dataflowPlan": dup_edge})) is None

    def test_empty_or_malformed_plan_fails_open(self):
        assert content.parse_parts(json.dumps({"dataflowPlan": self._plan(n_nodes=0)})) is None
        no_goal = self._plan()
        del no_goal["goal"]
        assert content.parse_parts(json.dumps({"dataflowPlan": no_goal})) is None
        bad_node = self._plan()
        del bad_node["nodes"][0]["intent"]
        assert content.parse_parts(json.dumps({"dataflowPlan": bad_node})) is None


class TestPlanTailDiagnosis:
    """dev/54 — verbose plan diagnosis: precise, model-correctable errors."""

    def test_non_plan_tails_are_not_diagnosed(self):
        assert content.plan_tail_diagnosis(None) is None
        assert content.plan_tail_diagnosis('{"suggestedPrompts": {"primary": "P"}}') is None
        assert content.plan_tail_diagnosis("just prose") is None

    def test_json_breakage_is_a_correctable_error(self):
        errors = content.plan_tail_diagnosis('{"dataflowPlan": {"goal": "g", nodes: []}}')
        assert errors and "not valid JSON" in errors[0]

    def test_broken_remove_only_body_is_diagnosed(self):
        # dev/61 — the removal keys mark a plan attempt too.
        errors = content.plan_tail_diagnosis('{"goal": "clear", "removeNodes": [old]}')
        assert errors and "not valid JSON" in errors[0]

    def test_field_errors_name_field_index_and_bound(self):
        import json as _json

        plan = {
            "goal": "g",
            "nodes": [
                {"ref": "n1", "nodeType": "curio.builtin/data-loading",
                 "title": "Load", "intent": "fine"},
                {"ref": "n1", "nodeType": "curio.builtin/data-loading",
                 "title": "dup", "intent": "fine"},
                {"ref": "n2", "nodeType": "curio.builtin/data-loading",
                 "title": "ok", "intent": "x" * 301},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
            "removeNodes": ["victim-1", "victim-1"],
        }
        errors = content.plan_tail_diagnosis(_json.dumps({"dataflowPlan": plan}))
        joined = "\n".join(errors)
        assert "nodes[2].intent is 301 chars (max 300)" in joined
        assert "refs must be unique" in joined
        assert "removeNodes[1] duplicates 'victim-1'" in joined

    def test_valid_plan_diagnoses_clean(self):
        import json as _json

        plan = {"goal": "g", "nodes": [
            {"ref": "n1", "nodeType": "curio.builtin/data-loading",
             "title": "Load", "intent": "load"},
        ], "edges": []}
        assert content.plan_tail_diagnosis(_json.dumps({"dataflowPlan": plan})) == []


class TestExtractPlanAttempt:
    """dev/56 — fence-agnostic plan-attempt recognition."""

    def _plan(self):
        return {"goal": "g", "nodes": [
            {"ref": "n1", "nodeType": "curio.builtin/data-loading",
             "title": "Load", "intent": "load"},
        ], "edges": []}

    def test_json_fence_mid_reply_with_trailing_prose(self):
        reply = (
            "Here is your plan:\n\n```json\n"
            + json.dumps({"dataflowPlan": self._plan()}, indent=2)
            + "\n```\n\nClick Apply above to place it."
        )
        stripped, raw = content.extract_plan_attempt(reply)
        assert raw == self._plan()
        assert "```" not in stripped
        assert "Here is your plan:" in stripped and "Click Apply above" in stripped

    def test_bare_fence_and_bare_plan_object(self):
        reply = "Plan:\n```\n" + json.dumps(self._plan()) + "\n```"
        _, raw = content.extract_plan_attempt(reply)
        assert raw == self._plan()

    def test_tool_request_form_in_json_fence(self):
        body = json.dumps({"toolRequest": {"tool": "dataflow.plan.write", "params": {"dataflowPlan": self._plan()}}})
        _, raw = content.extract_plan_attempt("x\n```json\n" + body + "\n```")
        assert raw == self._plan()

    def test_broken_json_planish_fence_returns_the_body(self):
        reply = 'Try:\n```json\n{"dataflowPlan": {"goal": "g", nodes: []}}\n```'
        stripped, raw = content.extract_plan_attempt(reply)
        assert isinstance(raw, str) and "dataflowPlan" in raw
        assert "```" not in stripped

    def test_non_plan_replies_untouched(self):
        reply = "Some code:\n```python\nprint(1)\n```"
        assert content.extract_plan_attempt(reply) == (reply, None)
        assert content.extract_plan_attempt("no fences at all") == ("no fences at all", None)

    def test_remove_only_bare_json_fence_is_recognized(self):
        # dev/61 — the "clear the canvas" leak: a bare remove-only plan
        # carries no "nodes" key at all.
        plan = {"goal": "clear the canvas",
                "removeNodes": ["old-loader", "cleaner"], "removeEdges": []}
        reply = (
            "Removing everything:\n\n```json\n"
            + json.dumps(plan, indent=2)
            + "\n```\n\nReview and apply the plan."
        )
        stripped, raw = content.extract_plan_attempt(reply)
        assert raw == plan
        assert "```" not in stripped and "Removing everything:" in stripped

    def test_remove_only_without_goal_is_still_claimed(self):
        # Claimed so the parser's goal error feeds the corrective round.
        plan = {"removeNodes": ["old-loader"]}
        _, raw = content.extract_plan_attempt("```json\n" + json.dumps(plan) + "\n```")
        assert raw == plan
        parsed, errors = content.parse_dataflow_plan_verbose(raw)
        assert parsed is None and any("goal" in e for e in errors)

    def test_broken_json_remove_only_fence_returns_the_body(self):
        reply = '```json\n{"goal": "clear", "removeNodes": [old-loader]}\n```'
        stripped, raw = content.extract_plan_attempt(reply)
        assert isinstance(raw, str) and "removeNodes" in raw
        assert "```" not in stripped


class TestExtractNodeContent:
    """dev/57 — only the executable content survives response formatting;
    legitimate content is never altered."""

    CODE = "import pandas as pd\ndf = pd.read_csv('x.csv')\nprint(df.head())"

    def test_fenced_with_prose_before_and_after(self):
        reply = f"Here is the code:\n\n```python\n{self.CODE}\n```\n\nThis loads the CSV."
        assert content.extract_node_content(reply) == self.CODE

    def test_language_identifiers_dropped(self):
        for lang in ("python", "json", "javascript", ""):
            assert content.extract_node_content(f"```{lang}\n{self.CODE}\n```") == self.CODE

    def test_largest_of_multiple_fences_wins(self):
        reply = f"Setup:\n```bash\npip install pandas\n```\nMain:\n```python\n{self.CODE}\n```"
        assert content.extract_node_content(reply) == self.CODE

    def test_json_wrapper_unwraps(self):
        import json as _json

        assert content.extract_node_content(_json.dumps({"content": self.CODE})) == self.CODE
        assert content.extract_node_content(_json.dumps({"code": self.CODE})) == self.CODE

    def test_wrapper_around_fence_unwraps_both(self):
        import json as _json

        wrapped = _json.dumps({"content": f"```python\n{self.CODE}\n```"})
        assert content.extract_node_content(wrapped) == self.CODE

    def test_unwrapped_code_is_byte_identical(self):
        assert content.extract_node_content(self.CODE) == self.CODE
        # A dict-literal in code (not a wrapper) stays untouched.
        code = 'config = {"content": "x", "code": "y"}\nrun(config)'
        assert content.extract_node_content(code) == code

    def test_not_controllable_sentinel_passes_through(self):
        assert content.extract_node_content("not controllable") == "not controllable"

    def test_non_string_and_empty(self):
        assert content.extract_node_content(None) == ""
        assert content.extract_node_content("   ") == ""


class TestDataflowPlanRevisionGrammar:
    """dev/59 — removeNodes/removeEdges + existing-id endpoints: additive
    plans byte-identical, remove-only plans valid, victims unreferencable."""

    def _plan(self, **over):
        plan = {
            "goal": "revise",
            "nodes": [
                {"ref": "a", "nodeType": "curio.builtin/computation-analysis",
                 "title": "New", "intent": "does new things"},
            ],
            "edges": [],
        }
        plan.update(over)
        return plan

    def test_additive_plans_are_byte_identical(self):
        (part,) = content.parse_parts(json.dumps({"dataflowPlan": self._plan()}))
        assert "removeNodes" not in part and "removeEdges" not in part

    def test_revision_fields_parse(self):
        plan = self._plan(
            removeNodes=["old-node-1"],
            removeEdges=["old-edge-1"],
            edges=[{"from": "a", "to": "existing-cleaner-id"}],
        )
        (part,) = content.parse_parts(json.dumps({"dataflowPlan": plan}))
        assert part["removeNodes"] == ["old-node-1"]
        assert part["removeEdges"] == ["old-edge-1"]
        assert part["edges"] == [{"from": "a", "to": "existing-cleaner-id"}]

    def test_to_handle_parses_and_stays_absent_when_unused(self):
        # dev/67-3: toHandle is optional shape — additive plans byte-identical.
        plan = {"goal": "g", "nodes": [
            {"ref": "a", "nodeType": "t", "title": "A", "intent": "i"},
            {"ref": "m", "nodeType": "curio.builtin/merge-flow", "title": "M", "intent": "i"},
        ], "edges": [
            {"from": "a", "to": "m", "toHandle": "in_2"},
        ]}
        part, errors = content.parse_dataflow_plan_verbose(plan)
        assert errors == []
        assert part["edges"] == [{"from": "a", "to": "m", "toHandle": "in_2"}]
        plan["edges"] = [{"from": "a", "to": "m"}]
        part, _ = content.parse_dataflow_plan_verbose(plan)
        assert part["edges"] == [{"from": "a", "to": "m"}]  # key only when used

    def test_to_handle_is_bounded(self):
        plan = {"goal": "g", "nodes": [
            {"ref": "a", "nodeType": "t", "title": "A", "intent": "i"},
            {"ref": "b", "nodeType": "t", "title": "B", "intent": "i"},
        ], "edges": [{"from": "a", "to": "b", "toHandle": "x" * 25}]}
        part, errors = content.parse_dataflow_plan_verbose(plan)
        assert part is None
        assert any("edges[0].toHandle" in e for e in errors)

    def test_remove_only_plan_is_valid(self):
        plan = {"goal": "cleanup", "removeNodes": ["old-1", "old-2"]}
        (part,) = content.parse_parts(json.dumps({"dataflowPlan": plan}))
        assert part["nodes"] == [] and part["removeNodes"] == ["old-1", "old-2"]

    def test_fully_empty_plan_stays_invalid(self):
        assert content.parse_parts(json.dumps({"dataflowPlan": {"goal": "g"}})) is None

    def test_edge_to_a_removal_victim_is_an_error(self):
        plan = self._plan(
            removeNodes=["victim-1"],
            edges=[{"from": "a", "to": "victim-1"}],
        )
        errors = content.plan_tail_diagnosis(json.dumps({"dataflowPlan": plan}))
        assert any("which this plan removes" in e for e in errors)

    def test_removal_duplicates_and_bounds(self):
        dup = self._plan(removeNodes=["x", "x"])
        errors = content.plan_tail_diagnosis(json.dumps({"dataflowPlan": dup}))
        assert any("duplicates 'x'" in e for e in errors)
        too_many = self._plan(removeNodes=[f"n{i}" for i in range(201)])
        errors = content.plan_tail_diagnosis(json.dumps({"dataflowPlan": too_many}))
        assert any("max 200" in e for e in errors)


class TestDecoratedRequest:
    """dev/90 A10 — the live two-block failure: a request block followed by a
    terminal suggestedPrompts block demoted the request to inert text."""

    REQUEST_BLOCK = ('```curio.v1\n{"delegateRequest": {"capability": '
                     '"node.kind.author", "inputs": {"look": "post-it"}}}\n```')
    PROMPTS_BLOCK = ('```curio.v1\n{"suggestedPrompts": '
                     '{"primary": "Check another city?"}}\n```')

    def test_decorated_request_wins_and_decorations_drop(self):
        reply = ("The weather is 73F.\n\nI will place a note.\n\n"
                 + self.REQUEST_BLOCK + "\n\n" + self.PROMPTS_BLOCK)
        visible, parts = content.extract_content(reply)
        assert [p["type"] for p in parts] == ["delegateRequest"]
        assert parts[0]["capability"] == "node.kind.author"
        assert "delegateRequest" not in visible  # the block executed, not shown
        assert "The weather is 73F." in visible

    def test_terminal_request_behavior_unchanged(self):
        reply = "prose\n\n" + self.REQUEST_BLOCK
        visible, parts = content.extract_content(reply)
        assert parts[0]["type"] == "delegateRequest"
        assert visible.strip() == "prose"

    def test_two_earlier_request_blocks_stay_conservative(self):
        reply = ("prose\n\n" + self.REQUEST_BLOCK + "\n\nmore\n\n"
                 + self.REQUEST_BLOCK + "\n\n" + self.PROMPTS_BLOCK)
        visible, parts = content.extract_content(reply)
        # One request per reply: ambiguity keeps the pre-A10 behavior.
        assert [p["type"] for p in parts] == ["suggestedPrompts"]
        assert visible.count("delegateRequest") == 2

    def test_no_terminal_block_stays_fail_open(self):
        reply = "prose\n\n" + self.REQUEST_BLOCK + "\n\ntrailing prose"
        visible, parts = content.extract_content(reply)
        assert parts == []
        assert "delegateRequest" in visible  # unchanged conservative boundary

    def test_terminal_decoration_without_any_request_unchanged(self):
        reply = "prose\n\n" + self.PROMPTS_BLOCK
        visible, parts = content.extract_content(reply)
        assert [p["type"] for p in parts] == ["suggestedPrompts"]
        assert visible.strip() == "prose"
