"""Tests for :mod:`utk_curio.backend.app.packages.build_models` (dev/89 commit 2).

The typed build contract: strict parsing, installer-rule path safety,
builder-owned file refusals, bounds, and content-addressed request identity.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from utk_curio.backend.app.packages import build_models
from utk_curio.backend.app.packages.build_models import (
    BuildRequestError,
    PackageBuildResult,
    parse_build_request,
    parse_build_result,
    request_digest,
)


def _request_payload(**overrides) -> dict:
    payload = {
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": {
            "id": "ai.test.demo",
            "compatibility": {"major": 1},
            "templates": [{"id": "demo-kind"}, {"id": "note-kind"}],
        },
        "files": {
            "sources/demo-kind.py": {"text": "return arg\n"},
            "sources/note.tsx": {"text": "export const x = 1\n"},
            "README.md": {"text": "# Demo\n"},
        },
        "behaviorEntries": ["sources/note.tsx"],
        "dependencies": {"python": {"pandas": ">=2.0"}, "js": {"marked": "12.0.0"}},
        "previewTemplates": ["note-kind"],
        "nodes": [
            {
                "templateId": "note-kind",
                "title": "Research note",
                "content": "findings...",
                "appearance": {"backgroundColor": "yellow"},
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestParseRequest:
    def test_happy_create(self):
        req = parse_build_request(_request_payload())
        assert req.mode == "create"
        assert req.target == "ai.test.demo@1"
        assert req.base_digest is None
        assert req.files["sources/demo-kind.py"] == b"return arg\n"
        assert req.behavior_entries == ("sources/note.tsx",)
        assert req.dependencies["python"] == {"pandas": ">=2.0"}
        assert req.preview_templates == ("note-kind",)
        assert req.nodes[0].template_id == "note-kind"
        # Normalized through the ONE shared appearance utility (dev/89 §3).
        assert req.nodes[0].appearance == {"backgroundColor": "#fef3c0"}
        assert req.timeout_class == "standard"

    def test_happy_extend_requires_base_digest(self):
        digest = "a" * 64
        req = parse_build_request(_request_payload(mode="extend", baseDigest=digest))
        assert req.mode == "extend" and req.base_digest == digest
        with pytest.raises(BuildRequestError, match="must pin baseDigest"):
            parse_build_request(_request_payload(mode="extend"))
        with pytest.raises(BuildRequestError, match="must pin baseDigest"):
            parse_build_request(_request_payload(mode="extend", baseDigest="ZZ" * 32))

    def test_create_refuses_base_digest(self):
        with pytest.raises(BuildRequestError, match="must not carry baseDigest"):
            parse_build_request(_request_payload(baseDigest="a" * 64))

    def test_unknown_keys_and_modes_refused(self):
        with pytest.raises(BuildRequestError, match="unknown keys"):
            parse_build_request(_request_payload(surprise=1))
        with pytest.raises(BuildRequestError, match="mode must be one of"):
            parse_build_request(_request_payload(mode="publish"))
        with pytest.raises(BuildRequestError, match="unsupported contractVersion"):
            parse_build_request(_request_payload(contractVersion="99"))

    def test_target_manifest_cross_check(self):
        with pytest.raises(BuildRequestError, match="does not match manifest coordinate"):
            parse_build_request(_request_payload(target="ai.test.other@1"))
        with pytest.raises(BuildRequestError, match="not a valid package coordinate"):
            parse_build_request(_request_payload(target="not a coordinate"))

    def test_target_is_optional_and_derived(self):
        # dev/90 A4: identity = manifest.id + compatibility.major; target is
        # redundant restatement, welcome but never required.
        payload = _request_payload()
        payload.pop("target")
        request = parse_build_request(payload)
        assert request.target == "ai.test.demo@1"

    def test_single_segment_id_error_names_the_grammar(self):
        # The live-transcript failure (dev/90 A4): 'curio-notes' LOOKS like a
        # valid '<packageId>@<major>' value — the refusal must say WHY it is
        # not, or the requester loops (as the Package Builder did).
        payload = _request_payload()
        payload["manifest"] = dict(payload["manifest"], id="curio-notes")
        payload.pop("target")
        with pytest.raises(BuildRequestError) as exc:
            parse_build_request(payload)
        message = str(exc.value)
        assert "reverse-DNS" in message
        assert "curio.notes" in message  # a fixable example
        # And the provided-target path gives the same diagnosis.
        payload["target"] = "curio-notes@1"
        with pytest.raises(BuildRequestError, match="reverse-DNS"):
            parse_build_request(payload)

    def test_unsafe_and_builder_owned_paths_refused(self):
        for bad in ("../evil.py", "/abs.py", "sources/../evil.py"):
            with pytest.raises((BuildRequestError, ValueError)):
                parse_build_request(_request_payload(files={bad: {"text": "x"}}))
        with pytest.raises(BuildRequestError, match="never rides the file map"):
            parse_build_request(_request_payload(files={"manifest.json": {"text": "{}"}}))
        with pytest.raises(BuildRequestError, match="never rides the file map"):
            parse_build_request(_request_payload(files={"integrity.json": {"text": "{}"}}))
        with pytest.raises(BuildRequestError, match="builder-owned"):
            parse_build_request(
                _request_payload(files={"scripts/behaviors.js": {"text": "x"}})
            )
        # Disallowed top-level bucket (installer layout rule).
        with pytest.raises(Exception, match="not allowed"):
            parse_build_request(_request_payload(files={"secrets/x.py": {"text": "x"}}))

    def test_file_entry_shapes_and_bounds(self):
        with pytest.raises(BuildRequestError, match="exactly one of"):
            parse_build_request(_request_payload(
                files={"sources/a.py": {"text": "x", "base64": "eA=="}}
            ))
        with pytest.raises(BuildRequestError, match="not valid base64"):
            parse_build_request(_request_payload(files={"icons/i.svg": {"base64": "@@"}}))
        decoded = parse_build_request(
            _request_payload(files={"icons/i.svg": {"base64": base64.b64encode(b"<svg/>").decode()}},
                             behaviorEntries=[], previewTemplates=[], nodes=[])
        )
        assert decoded.files["icons/i.svg"] == b"<svg/>"
        big = "x" * (build_models.MAX_FILE_BYTES + 1)
        with pytest.raises(BuildRequestError, match="per-file limit"):
            parse_build_request(_request_payload(files={"sources/a.py": {"text": big}}))
        too_many = {f"sources/f{i}.py": {"text": "x"} for i in range(build_models.MAX_FILES + 1)}
        with pytest.raises(BuildRequestError, match="file limit"):
            parse_build_request(_request_payload(files=too_many))

    def test_behavior_entries_validated(self):
        with pytest.raises(BuildRequestError, match="not present in files"):
            parse_build_request(_request_payload(behaviorEntries=["sources/ghost.tsx"]))
        with pytest.raises(BuildRequestError, match="must live under sources/"):
            parse_build_request(_request_payload(
                files={"starters/note.tsx": {"text": "x"}},
                behaviorEntries=["starters/note.tsx"],
            ))
        with pytest.raises(BuildRequestError, match="must end in one of"):
            parse_build_request(_request_payload(behaviorEntries=["sources/demo-kind.py"]))

    def test_dependencies_validated(self):
        with pytest.raises(BuildRequestError, match="unknown ecosystems"):
            parse_build_request(_request_payload(dependencies={"npm": {}}))
        with pytest.raises(BuildRequestError, match="invalid name"):
            parse_build_request(_request_payload(dependencies={"js": {"bad name": "1"}}))
        with pytest.raises(BuildRequestError, match="constraint must be"):
            parse_build_request(_request_payload(dependencies={"js": {"marked": ""}}))

    def test_preview_and_nodes_grounded_in_manifest(self):
        with pytest.raises(BuildRequestError, match="not declared by the draft manifest"):
            parse_build_request(_request_payload(previewTemplates=["ghost-kind"]))
        with pytest.raises(BuildRequestError, match="not declared by the draft manifest"):
            parse_build_request(_request_payload(
                nodes=[{"templateId": "ghost-kind"}]
            ))
        # Extend mode defers node-template membership to the merge planner
        # (the node may target a preserved base template).
        req = parse_build_request(_request_payload(
            mode="extend", baseDigest="b" * 64,
            nodes=[{"templateId": "base-kind"}],
        ))
        assert req.nodes[0].template_id == "base-kind"

    def test_appearance_normalized_by_shared_utility(self):
        with pytest.raises(BuildRequestError, match="unknown keys"):
            parse_build_request(_request_payload(
                nodes=[{"templateId": "note-kind", "appearance": {"color": "red"}}]
            ))
        with pytest.raises(BuildRequestError, match="whitespace"):
            parse_build_request(_request_payload(
                nodes=[{"templateId": "note-kind",
                        "appearance": {"backgroundColor": "a\nb"}}]
            ))
        with pytest.raises(BuildRequestError, match="exceeds"):
            parse_build_request(_request_payload(
                nodes=[{"templateId": "note-kind",
                        "appearance": {"backgroundColor": "x" * 65}}]
            ))
        # Palette names and valid six-digit hex normalize; junk refuses.
        pink = parse_build_request(_request_payload(
            nodes=[{"templateId": "note-kind",
                    "appearance": {"backgroundColor": "PINK"}}]))
        assert pink.nodes[0].appearance == {"backgroundColor": "#fbd3e0"}
        with pytest.raises(BuildRequestError, match="refused|not a palette"):
            parse_build_request(_request_payload(
                nodes=[{"templateId": "note-kind",
                        "appearance": {"backgroundColor": "rgb(1,2,3)"}}]
            ))


class TestRequestDigest:
    def test_stable_across_key_order(self):
        a = parse_build_request(_request_payload())
        shuffled = dict(reversed(list(_request_payload().items())))
        b = parse_build_request(shuffled)
        assert request_digest(a) == request_digest(b)

    def test_changes_with_content(self):
        base = request_digest(parse_build_request(_request_payload()))
        changed_file = parse_build_request(_request_payload(files={
            "sources/demo-kind.py": {"text": "return arg  # changed\n"},
            "sources/note.tsx": {"text": "export const x = 1\n"},
            "README.md": {"text": "# Demo\n"},
        }))
        assert request_digest(changed_file) != base
        changed_node = parse_build_request(_request_payload(nodes=[
            {"templateId": "note-kind", "appearance": {"backgroundColor": "pink"}}
        ]))
        assert request_digest(changed_node) != base

    def test_digest_is_sha256_hex(self):
        digest = request_digest(parse_build_request(_request_payload()))
        assert len(digest) == 64 and int(digest, 16) >= 0


class TestBuildResult:
    def test_round_trip(self):
        result = PackageBuildResult(
            status="ready",
            input_digest="c" * 64,
            base_digest="d" * 64,
            artifact_digest=hashlib.sha256(b"zip").hexdigest(),
            builder_version="toolchain-1",
            diff={"files": {"added": ["sources/a.py"]}},
            dependencies={"js": {"marked": "12.0.0"}},
            policy_findings=("warn: unpinned python dep",),
            archive_size=123,
            warnings=("w",),
            logs=("compiled",),
        )
        parsed = parse_build_result(result.to_payload())
        assert parsed == result

    def test_ready_requires_artifact_digest(self):
        payload = PackageBuildResult(status="ready", input_digest="c" * 64,
                                     artifact_digest="e" * 64).to_payload()
        payload["artifactDigest"] = None
        with pytest.raises(BuildRequestError, match="ready result must carry"):
            parse_build_result(payload)

    def test_failed_refuses_artifact_digest(self):
        payload = PackageBuildResult(status="failed", input_digest="c" * 64).to_payload()
        payload["artifactDigest"] = "e" * 64
        with pytest.raises(BuildRequestError, match="failed result must not"):
            parse_build_result(payload)

    def test_bad_status_and_digests(self):
        with pytest.raises(BuildRequestError, match="status must be one of"):
            parse_build_result({"status": "done", "inputDigest": "c" * 64})
        with pytest.raises(BuildRequestError, match="inputDigest"):
            parse_build_result({"status": "failed", "inputDigest": "nope"})
