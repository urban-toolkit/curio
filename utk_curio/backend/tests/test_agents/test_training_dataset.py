"""dev/122 — the training set and the consent that has to precede it.

What is asserted here is mostly what CANNOT happen: an unapproved prompt, a
held-out fixture, a target the runtime's parser would refuse, an interaction-
edge fixture trained on a weakened graph, a row that still looks credentialed,
or an upload consented to for a different set.

Offline: values in, values out. No store, no provider, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import builtin, content as content_mod
from utk_curio.backend.app.agents import source_grounding
from utk_curio.backend.app.agents.evaluation import export as export_mod
from utk_curio.backend.app.agents.evaluation import oracle
from utk_curio.backend.app.agents.evaluation.fixtures import (
    Fixture,
    fixture_paths,
    load_fixture,
)
from utk_curio.backend.app.agents.evaluation.report import scrub
from utk_curio.backend.app.agents.training import consent as consent_mod
from utk_curio.backend.app.agents.training import dataset as dataset_mod

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES = [load_fixture(path) for path in fixture_paths()]
INSTRUCTION = builtin.read_instruction_text(dataset_mod.DFB_COORD) or ""
PREAMBLE = builtin.read_prompt_text(dataset_mod.DFB_COORD, "system")
TAIL = content_mod.tail_instruction()
ROSTER = "Available node templates (a node.create nodeType or a plan nodeType MUST be one of these ids):\n- curio.builtin/data-loading — Data Loading"


def _approved(fixture: Fixture, *, split: str = "train", consent: dict | None = None) -> Fixture:
    data = json.loads(json.dumps(fixture.data))
    data["review"] = {
        "status": "approved", "draftedBy": data["review"].get("draftedBy"),
        "reviewedBy": "the owner", "reviewedAt": "2026-09-09T00:00:00Z",
    }
    data["split"] = split
    if consent is not None:
        data["consent"] = consent
    return Fixture(path=fixture.path, data=data)


def _build(fixtures, **overrides):
    kwargs = dict(
        split="train",
        instruction=INSTRUCTION,
        preamble=PREAMBLE,
        tail=TAIL,
        roster=ROSTER,
        scrub=scrub,
        credential_finder=source_grounding.credential_literals,
        parse_reply=dataset_mod.plan_target_check,
    )
    kwargs.update(overrides)
    return dataset_mod.build_training_set(fixtures, **kwargs)


def _representable():
    return [f for f in FIXTURES if "interaction-edge" not in f.needs]


class TestTheGatesAreGates:
    def test_nothing_builds_while_the_corpus_is_unreviewed(self):
        """The shipped state. An export refuses and says why, so a fresh
        install cannot train on prompts no person has approved."""
        assert all(not f.approved for f in FIXTURES)
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build(FIXTURES)
        assert "awaiting review" in str(refusal.value)

    @pytest.mark.parametrize("split", ["heldout", "validation"])
    def test_the_evaluation_splits_are_refused_by_name(self, split):
        approved = [_approved(f, split=split) for f in _representable()]
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build(approved, split=split)
        assert "may not draw from" in str(refusal.value)

    def test_only_the_train_split_contributes_rows(self):
        approved = [
            _approved(f, split="train" if index % 2 == 0 else "heldout")
            for index, f in enumerate(_representable())
        ]
        built = _build(approved)
        wanted = {f.fixture_id for f in approved if f.split == "train"}
        assert set(built.fixture_ids) <= wanted

    def test_a_missing_instruction_refuses_rather_than_composing_a_stub(self):
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build([_approved(FIXTURES[0])], instruction="")
        assert "no instruction prompt" in str(refusal.value)

    def test_user_content_is_ineligible_until_it_has_a_consent_surface(self):
        """OQ-010's posture: unclassified or user-authored content is not
        eligible for remote egress. F2 owns the surface that would change it."""
        fixture = _approved(
            FIXTURES[0], consent={"dataContent": "user-content", "licence": "theirs"}
        )
        with pytest.raises(dataset_mod.TrainingSetRefused):
            _build([fixture])
        others = [_approved(f) for f in _representable()[:4]]
        built = _build(others + [fixture])
        assert fixture.fixture_id not in built.fixture_ids
        assert any(
            e.fixture_id == fixture.fixture_id and "user-content" in e.reason
            for e in built.excluded
        )


class TestTheTargetIsTheRuntimesContract:
    def test_every_target_parses_through_the_production_parser(self):
        built = _build([_approved(f) for f in _representable()])
        assert built.rows
        for row in built.rows:
            ok, detail = dataset_mod.plan_target_check(row["messages"][-1]["content"])
            assert ok, detail

    def test_a_target_the_parser_would_refuse_is_excluded_with_its_reason(self):
        """The rule that matters most: teaching a model to emit blocks the
        runtime refuses is worse than teaching it nothing."""
        def _always_refuse(reply):
            return False, "the parser would refuse this"

        approved = [_approved(f) for f in _representable()[:3]]
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build(approved, parse_reply=_always_refuse)
        assert "does not parse" in str(refusal.value)

    def test_interaction_edge_fixtures_are_excluded_by_construction(self):
        gaps = [f for f in FIXTURES if "interaction-edge" in f.needs]
        assert len(gaps) == 8
        built = _build([_approved(f) for f in FIXTURES])
        for fixture in gaps:
            assert fixture.fixture_id not in built.fixture_ids
        assert {
            e.reason for e in built.excluded if e.reason == "interaction-edge"
        } == {"interaction-edge"}

    def test_the_row_shape_is_the_chat_shape_with_the_prompt_as_the_user_turn(self):
        fixture = _approved(_representable()[0])
        built = _build([fixture])
        row = built.rows[0]
        roles = [m["role"] for m in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        assert row["messages"][1]["content"].startswith(fixture.prompt[:40])
        assert "dataflowPlan" in row["messages"][2]["content"]

    def test_the_system_turn_carries_the_runtimes_own_pieces_in_its_order(self):
        built = _build([_approved(_representable()[0])])
        system = built.rows[0]["messages"][0]["content"]
        assert INSTRUCTION.strip() in system
        assert TAIL.strip() in system
        assert ROSTER.strip() in system
        assert system.index(INSTRUCTION.strip()) < system.index(TAIL.strip())
        assert system.index(TAIL.strip()) < system.index(ROSTER.strip())

    def test_the_roster_block_comes_from_the_runtimes_formatter(self):
        """dev/122 §3.2 property 3, and DEC-062: a hand-written roster
        paragraph would be a prompt shape the runtime never sends."""
        from utk_curio.backend.app.agents import services

        rows = [{
            "id": "curio.builtin/data-loading", "label": "Data Loading",
            "description": "load", "authorable": True, "inputs": [1],
            "maxIncomingEdges": 1,
        }]
        block = services.roster_block(rows)
        assert block and "curio.builtin/data-loading" in block
        assert "Available node templates" in block


class TestDigestsAndBounds:
    def test_the_digest_is_stable_and_moves_with_the_prompt(self):
        approved = [_approved(f) for f in _representable()[:3]]
        first = _build(approved).sha256
        assert first == _build(approved).sha256
        changed = json.loads(json.dumps(approved[0].data))
        changed["prompt"] = changed["prompt"] + " Also chart the totals."
        moved = _build(
            [Fixture(path=approved[0].path, data=changed)] + approved[1:]
        ).sha256
        assert moved != first

    def test_the_digest_moves_with_the_instruction(self):
        approved = [_approved(f) for f in _representable()[:2]]
        assert _build(approved).sha256 != _build(
            approved, instruction=INSTRUCTION + "\n\nAlso be brief."
        ).sha256

    def test_the_instruction_digest_is_recorded(self):
        built = _build([_approved(_representable()[0])])
        assert len(built.instruction_sha256) == 64
        assert len(built.roster_digest) == 64

    def test_the_jsonl_is_one_object_per_line(self):
        built = _build([_approved(f) for f in _representable()[:3]])
        lines = built.jsonl.strip().splitlines()
        assert len(lines) == len(built.rows)
        for line in lines:
            assert set(json.loads(line)) == {"messages"}

    def test_a_set_larger_than_the_bound_is_refused(self, monkeypatch):
        monkeypatch.setattr(dataset_mod, "MAX_ROWS", 2)
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build([_approved(f) for f in _representable()[:5]])
        assert "exceeds the 2-row bound" in str(refusal.value)


class TestNothingCredentialedIsUploaded:
    def test_a_credential_that_survives_scrubbing_refuses_the_build(self):
        fixture = _approved(_representable()[0])
        poisoned = json.loads(json.dumps(fixture.data))
        poisoned["prompt"] = (
            fixture.prompt + ' Use api_key = "sk-abcdefghijklmnopqrstuvwxyz012345".'
        )
        with pytest.raises(dataset_mod.TrainingSetRefused) as refusal:
            _build(
                [Fixture(path=fixture.path, data=poisoned)],
                scrub=lambda text: text,   # a scrubber that does nothing
            )
        assert "survived scrubbing" in str(refusal.value)
        assert "refusing to upload" in str(refusal.value)

    def test_the_real_scrubber_redacts_and_the_build_then_proceeds(self):
        fixture = _approved(_representable()[0])
        poisoned = json.loads(json.dumps(fixture.data))
        poisoned["prompt"] = (
            fixture.prompt + ' The token is token = "ghp_abcdefghijklmnopqrstuvwxyz12".'
        )
        built = _build([Fixture(path=fixture.path, data=poisoned)])
        blob = built.jsonl
        assert "ghp_abcdefghijklmnopqrstuvwxyz12" not in blob
        assert "redacted" in blob

    def test_no_shipped_fixture_produces_a_credentialed_row(self):
        built = _build([_approved(f) for f in _representable()])
        assert built.rows


class TestTheShippedFixturesDeclareTheirClassification:
    @pytest.mark.parametrize("fixture", FIXTURES, ids=[f.fixture_id for f in FIXTURES])
    def test_every_fixture_declares_identifiers_only_and_its_licence(self, fixture):
        consent = fixture.data.get("consent")
        assert isinstance(consent, dict), "a fixture must declare what an export carries"
        assert consent["dataContent"] == "identifiers-only"
        assert consent["licence"]

    @pytest.mark.parametrize(
        "fixture",
        [f for f in FIXTURES if f.required["datasets"]],
        ids=lambda f: f.fixture_id,
    )
    def test_a_fixture_that_names_datasets_records_their_licences(self, fixture):
        """Recorded so a reader can see they were considered — they are not
        implicated by an export that carries identifiers only."""
        declared = {
            row["datasetId"]: row["licence"]
            for row in fixture.data["consent"].get("sourceLicences") or []
        }
        assert set(declared) == set(fixture.required["datasets"])
        catalog = {}
        for manifest in (REPO_ROOT / "datasets").glob("*/manifest.json"):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("id"):
                catalog[data["id"]] = data.get("license") or ""
        for dataset_id, licence in declared.items():
            assert licence == catalog.get(dataset_id), dataset_id

    def test_the_schema_declares_consent_and_still_forbids_unknown_keys(self):
        schema = json.loads(
            (REPO_ROOT / "docs/schemas/example-prompt-fixture.v1.json").read_text(
                encoding="utf-8"
            )
        )
        assert "consent" in schema["properties"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["consent"]["properties"]["dataContent"]["enum"] == [
            "identifiers-only", "user-content",
        ]


class TestConsent:
    def _statement(self):
        built = _build([_approved(f) for f in _representable()[:3]])
        return built, consent_mod.statement_for(
            built, base_url="http://api.example.com/v1", api_type="openai_compatible",
            licences={f: "MIT (this repository)" for f in built.fixture_ids},
        )

    def test_the_statement_names_the_host_the_rows_and_the_licences(self):
        built, statement = self._statement()
        payload = statement.as_dict()
        assert payload["destinationHost"] == "api.example.com"
        assert payload["rows"] == len(built.rows)
        assert payload["bytes"] == built.bytes_len
        assert payload["rowsDigest"] == built.sha256
        assert len(payload["licences"]) == len(built.fixture_ids)
        assert "identifiers" in payload["note"].lower()
        assert "Sends" in payload["sentence"]

    def test_the_statement_carries_no_url_and_no_key(self):
        built = _build([_approved(_representable()[0])])
        statement = consent_mod.statement_for(
            built, base_url="https://api.example.com/v1?api_key=sk-secret-value-1234",
            api_type="openai_compatible",
        )
        blob = json.dumps(statement.as_dict())
        assert "sk-secret-value-1234" not in blob
        assert "/v1" not in blob
        assert "api.example.com" in blob

    def test_an_endpoint_with_no_base_url_is_named_by_kind(self):
        assert consent_mod.host_of("", "openai_compatible") == (
            "the default openai_compatible endpoint"
        )

    def test_consent_requires_an_explicit_confirmation(self):
        _built, statement = self._statement()
        with pytest.raises(consent_mod.ConsentRefused) as refusal:
            consent_mod.grant(
                statement, user_key="1", echoed_digest=statement.rows_digest,
                confirmed=False,
            )
        assert "explicit confirmation" in str(refusal.value)

    def test_consent_must_echo_the_digest_it_was_shown(self):
        _built, statement = self._statement()
        with pytest.raises(consent_mod.ConsentRefused):
            consent_mod.grant(
                statement, user_key="1", echoed_digest="", confirmed=True
            )
        with pytest.raises(consent_mod.ConsentRefused) as refusal:
            consent_mod.grant(
                statement, user_key="1", echoed_digest="d" * 64, confirmed=True
            )
        assert "changed since it was shown" in str(refusal.value)

    def test_a_granted_consent_records_who_what_when_and_where(self):
        _built, statement = self._statement()
        record = consent_mod.grant(
            statement, user_key="1", echoed_digest=statement.rows_digest,
            confirmed=True,
        ).as_dict()
        assert record["grantedBy"] == "1"
        assert record["grantedAt"]
        assert record["rowsDigest"] == statement.rows_digest
        assert record["destinationHost"] == "api.example.com"
        assert "identifiers" in record["statement"].lower()

    def test_a_set_that_changed_cannot_reuse_an_earlier_consent(self):
        """The digest is the whole point: a fixture approved or edited between
        the preview and the click changes what would be sent."""
        first = _build([_approved(f) for f in _representable()[:3]])
        second = _build([_approved(f) for f in _representable()[:4]])
        assert first.sha256 != second.sha256
        statement = consent_mod.statement_for(second, base_url="http://h/v1")
        with pytest.raises(consent_mod.ConsentRefused):
            consent_mod.grant(
                statement, user_key="1", echoed_digest=first.sha256, confirmed=True
            )
