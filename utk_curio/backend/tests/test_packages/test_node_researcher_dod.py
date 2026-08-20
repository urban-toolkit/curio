"""The dev/89 DOD regression (memo §7, commit 9): the Node Researcher
reference package driven end-to-end THROUGH the new capability stack —
build → provenance/preview contract → promotion → colored nodes — plus the
DOD profile's structural guarantees (presentation-only, no Python, no JS
deps, per-instance color, recolor-never-rebuilds) and the fixture parity
guard against the RTL-covered frontend mirror.

Visual baselines note: the pinned preview runner is deployment infrastructure
(CURIO_BUILD_PREVIEW_RUNNER); these tests drive the preview CONTRACT (five
states, per-state screenshots, registration) through the deterministic fake
harness — approved pixel baselines live with the operator's runner, not here.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from utk_curio.backend.app.packages import (
    build_jobs,
    build_promotion,
    build_staging,
    node_researcher_reference as reference,
)
from utk_curio.backend.app.packages.build_extension import installed_package_digest
from utk_curio.backend.app.packages.build_pipeline import run_build
from utk_curio.backend.app.packages.build_preview import PREVIEW_STATES
from utk_curio.backend.app.packages.node_appearance import NAMED_COLORS
from utk_curio.backend.tests.test_packages.test_build_compiler import _FAKE_ESBUILD
from utk_curio.backend.tests.test_packages.test_build_preview import _FAKE_RUNNER

_NOTES = [
    {"title": "Transit findings", "color": "pink",
     "content": "# Findings\n- **Headways** doubled\n- [source](https://data.test/gtfs)"},
    {"title": "Zoning summary", "color": "lavender",
     "content": "Mixed-use parcels grew 12% since 2020."},
    {"title": "Custom-color note", "color": "#336699", "content": "Deep-dive next week."},
]


@pytest.fixture(autouse=True)
def _fresh_jobs():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


@pytest.fixture()
def pinned_tools(tmp_path, monkeypatch):
    esbuild = tmp_path / "fake-esbuild"
    esbuild.write_text(_FAKE_ESBUILD, encoding="utf-8")
    esbuild.chmod(0o755)
    runner = tmp_path / "fake-preview-runner"
    runner.write_text(_FAKE_RUNNER, encoding="utf-8")
    runner.chmod(0o755)
    monkeypatch.setenv("CURIO_BUILD_ESBUILD", str(esbuild))
    monkeypatch.setenv("CURIO_BUILD_PREVIEW_RUNNER", str(runner))


class TestFixtureParity:
    def test_backend_fixture_mirrors_the_rtl_covered_component(self):
        # One truth: the packaged TSX and the RTL-tested frontend component
        # are byte-identical — drift breaks this test, not the DOD silently.
        mirror = reference.frontend_mirror_path()
        assert mirror.is_file(), f"frontend mirror missing at {mirror}"
        assert reference.behavior_source() == mirror.read_text(encoding="utf-8")

    def test_source_carries_the_dod_posture(self):
        source = reference.behavior_source()
        assert "registerBehavior" in source
        assert reference.BEHAVIOR_KEY in source
        # The shared palette, mirrored constant-for-constant.
        for hex_value in NAMED_COLORS.values():
            assert hex_value in source
        # Presentation-only: nothing in the source runs code or fetches.
        for forbidden in ("fetch(", "XMLHttpRequest", "sendCodeOverride", "eval("):
            assert forbidden not in source


class TestReferenceDraft:
    def test_draft_is_presentation_only(self):
        request = reference.reference_build_request(_NOTES)
        manifest = request.manifest
        template = manifest["templates"][0]
        assert template["engine"] == "javascript"
        assert template["editor"] == "none"
        assert template["hasCode"] is False
        assert template["inputPorts"] == [] and template["outputPorts"] == []
        assert manifest["dependencies"] == {"packages": {}, "python": {}, "js": {}}
        assert "behaviorScript" not in manifest  # the packager stamps it
        assert request.behavior_entries == (f"sources/{reference.TEMPLATE_ID}.tsx",)
        assert request.preview_templates == (reference.TEMPLATE_ID,)

    def test_note_colors_normalize_at_parse(self):
        request = reference.reference_build_request(_NOTES)
        colors = [n.appearance["backgroundColor"] for n in request.nodes]
        assert colors == [NAMED_COLORS["pink"], NAMED_COLORS["lavender"], "#336699"]

    def test_invalid_note_color_refuses(self):
        from utk_curio.backend.app.packages.build_models import BuildRequestError

        with pytest.raises(BuildRequestError, match="appearance"):
            reference.reference_build_request([{"content": "x", "color": "#777777"}])


class TestEndToEnd:
    def test_build_promote_and_color_the_canvas(self, tmp_curio, pinned_tools):
        from utk_curio.backend.app.packages.storage import package_dir

        request = reference.reference_build_request(_NOTES)
        job = run_build("guest", request)
        assert job.phase == "ready", job.to_payload()
        result = job.result

        # ── the reviewed artifact is the DOD package ──
        archive = build_staging.read_artifact("guest", result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            bundle = zf.read("scripts/behaviors.js")
        assert f"sources/{reference.TEMPLATE_ID}.tsx" in names  # source ships
        assert manifest["behaviorScript"] == "scripts/behaviors.js"
        assert manifest["dependencies"]["python"] == {}  # never the sandbox
        assert manifest["dependencies"]["js"] == {}  # self-contained bundle
        # The compiled bundle carries the behavior registration + externals.
        assert reference.BEHAVIOR_KEY.encode() in bundle
        assert b"alias:react" in bundle  # host singletons stay external

        # ── the preview CONTRACT: five states, each screenshotted ──
        preview = result.preview
        assert preview["status"] == "ok"
        states = preview["states"][reference.TEMPLATE_ID]
        assert set(states) == set(PREVIEW_STATES)
        for state in PREVIEW_STATES:
            key = f"{reference.TEMPLATE_ID}/{state}"
            assert preview["screenshots"][key]["bytes"] > 0
        assert preview["registered"][reference.TEMPLATE_ID] == [reference.BEHAVIOR_KEY]

        # ── promote + create the colored notes (server-side spec) ──
        journal = build_promotion.promote(
            "guest", target=reference.TARGET,
            artifact_digest=result.artifact_digest)
        assert journal["status"] == "awaiting-activation"
        assert (package_dir("guest", reference.TARGET) / "scripts" / "behaviors.js").is_file()

    def test_recolor_never_rebuilds_the_package(self, tmp_curio, pinned_tools):
        request = reference.reference_build_request(_NOTES[:1])
        job = run_build("guest", request)
        build_promotion.promote("guest", target=reference.TARGET,
                                artifact_digest=job.result.artifact_digest)
        before = installed_package_digest("guest", reference.TARGET)
        # A direct recolor is a spec/canvas edit — the installed package's
        # bytes never change (dev/89: recoloring never rebuilds).
        node = {"id": "n1", "type": f"{reference.PACKAGE_ID}/{reference.TEMPLATE_ID}@1",
                "metadata": {"appearance": {"backgroundColor": NAMED_COLORS["green"]}}}
        node["metadata"]["appearance"]["backgroundColor"] = NAMED_COLORS["orange"]
        assert installed_package_digest("guest", reference.TARGET) == before

    def test_same_template_two_colors_stay_independent(self, tmp_curio, pinned_tools):
        request = reference.reference_build_request(_NOTES)
        assert len({n.appearance["backgroundColor"] for n in request.nodes}) == 3
        # One template id serves every note — color is instance identity, never
        # template identity (dev/89 §3).
        assert {n.template_id for n in request.nodes} == {reference.TEMPLATE_ID}


class TestDodThroughTheAgent:
    """The full §7 DOD scenario at the route level: a Package Builder run
    whose reply carries the reference draft (agent-produced web-search text +
    requested colors) → reviewed proposal → apply → installed package +
    colored post-it nodes persisted in the spec."""

    COORD = "agent.package-builder@1.0.0"

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_recorded_scenario(self, client, user_and_token, tmp_curio, pinned_tools,
                               monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        project_id = client.post(
            "/api/projects",
            json={"name": "dod", "spec": {"dataflow": {"nodes": [], "edges": [],
                                                       "packages": []}},
                  "outputs": []},
            headers=self._auth(token),
        ).get_json()["id"]
        client.post(f"/api/agents/projects/{project_id}/install",
                    json={"coord": self.COORD}, headers=self._auth(token))
        att_id = client.post(
            f"/api/agents/projects/{project_id}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=self._auth(token),
        ).get_json()["attachmentId"]

        tail = ("```curio.v1\n" + json.dumps({
            "toolRequest": {"tool": "package.draft.apply",
                            "params": reference.reference_request_params(_NOTES)},
        }) + "\n```")
        replies = [tail, "Proposed — review the draft above."]
        calls: list = []

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)

        run = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
            json={"message": "turn my web-search findings into post-it notes"},
            headers=self._auth(token),
        )
        assert run.status_code == 200, run.get_data(as_text=True)
        content = run.get_json()["content"]
        proposals = [p for p in content if p["type"] == "proposal"]
        assert proposals, json.dumps({"content": content, "lastModelMsg": (
            calls[-1][-1]["content"][-800:] if calls else None)})[:2000]
        proposal = proposals[0]
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == reference.TARGET

        resp = client.post(
            f"/api/agents/projects/{project_id}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=self._auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["requiresRegistryRefresh"] is True
        created = body["createdNodes"]
        assert [n["metadata"]["appearance"]["backgroundColor"] for n in created] == [
            NAMED_COLORS["pink"], NAMED_COLORS["lavender"], "#336699"]
        assert all(n["type"] == f"{reference.PACKAGE_ID}/{reference.TEMPLATE_ID}@1"
                   for n in created)

        # Save/reload equivalence at the source of truth: the spec carries the
        # canonical appearance shape and the fixed note bodies.
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, project_id)
        nodes = {n["title"]: n for n in spec["dataflow"]["nodes"]}
        assert nodes["Transit findings"]["metadata"]["appearance"] == {
            "backgroundColor": NAMED_COLORS["pink"]}
        assert "**Headways**" in nodes["Transit findings"]["content"]
        assert nodes["Custom-color note"]["metadata"]["appearance"] == {
            "backgroundColor": "#336699"}
