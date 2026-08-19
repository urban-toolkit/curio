"""Typed package-build contract — immutable request/result models (memo dev/89 §3.1/§3.8).

The agent-facing package build service (dev/89) never consumes a raw model
draft directly: every build starts from a validated, bounded, content-addressed
:class:`PackageBuildRequest`, and every finished build is described by a
:class:`PackageBuildResult` whose digests identify the exact reviewed artifact.

Invariants owned here (dev/89 §3.1):

* **Strict shape** — unknown top-level keys, malformed paths, missing modes,
  and out-of-policy sizes fail parsing loudly. Nothing is silently dropped.
* **Same path rules as install time** — file paths run through the
  installer's safe-segment + allowed-layout checks (one truth, the same
  posture as ``delegation._resolve_definition``-style private reuse), so a
  request can never describe an archive the installer would reject.
* **Builder-owned artifacts stay builder-owned** — ``manifest.json`` and
  ``integrity.json`` never ride the file map (the manifest is a typed field;
  integrity is generated), and ``scripts/`` is refused: compiled behavior
  bundles come from the build service's compiler, never from the model.
* **Content-addressed identity** — :func:`request_digest` hashes the
  normalized request (file bodies by their own SHA-256), so identical
  requests are identical builds: retries are idempotent and results
  cacheable by input digest (dev/89 §3.9).

Color note: a requested node's ``appearance`` is bounds-checked here only
(shape, key set, length). Palette/hex normalization and contrast derivation
belong to the ONE shared node-appearance utility (dev/89 §3, lands with the
apply/frontend slice) — duplicating it here would fork the validation truth.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from utk_curio.backend.app.packages.installer import (
    _check_allowed_layout,
    _safe_member_path,
)
from utk_curio.backend.app.packages.storage import PACKAGE_DIR_RE, TEMPLATE_ID_RE

BUILD_CONTRACT_VERSION = "1"

_MODES = ("create", "extend")
_TIMEOUT_CLASSES = ("quick", "standard")
_RESULT_STATUSES = ("ready", "failed")

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# Request bounds (dev/89 §3.1: number of files/templates, path length,
# individual/total source size, dependency count, timeout class). Packages
# are template-and-asset oriented; anything larger travels out-of-band.
MAX_FILES = 64
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PATH_CHARS = 240
MAX_BEHAVIOR_ENTRIES = 4
MAX_DEPENDENCIES_PER_ECOSYSTEM = 32
MAX_DEPENDENCY_NAME_CHARS = 100
MAX_DEPENDENCY_CONSTRAINT_CHARS = 100
MAX_PREVIEW_TEMPLATES = 16
MAX_REQUESTED_NODES = 16
MAX_NODE_TITLE_CHARS = 200
MAX_NODE_GOAL_CHARS = 2_000
MAX_NODE_CONTENT_CHARS = 200_000
MAX_APPEARANCE_VALUE_CHARS = 64

_BEHAVIOR_ENTRY_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")
_DEPENDENCY_ECOSYSTEMS = ("python", "js", "packages")

_REQUEST_KEYS = frozenset({
    "contractVersion", "mode", "target", "baseDigest", "manifest", "files",
    "behaviorEntries", "dependencies", "previewTemplates", "nodes",
    "timeoutClass",
})
_NODE_KEYS = frozenset({"templateId", "title", "content", "goal", "appearance"})
_FILE_ENTRY_KEYS = frozenset({"text", "base64"})


class BuildRequestError(ValueError):
    """Raised when a build request or result payload fails validation."""


@dataclass(frozen=True)
class RequestedNode:
    """One node instance to create after the reviewed install succeeds."""

    template_id: str
    title: str | None = None
    content: str | None = None
    goal: str | None = None
    # Bounds-checked shape only ({"backgroundColor": "<short string>"}) —
    # value normalization is the shared node-appearance utility's job.
    appearance: dict[str, str] | None = None

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"templateId": self.template_id}
        if self.title is not None:
            out["title"] = self.title
        if self.content is not None:
            out["content"] = self.content
        if self.goal is not None:
            out["goal"] = self.goal
        if self.appearance is not None:
            out["appearance"] = dict(self.appearance)
        return out


@dataclass(frozen=True)
class PackageBuildRequest:
    """A validated, immutable build input (dev/89 §3.1).

    ``files`` maps archive-relative POSIX paths to raw bytes — every path has
    already passed the installer's safety and layout rules. The manifest dict
    is the draft manifest verbatim; deep schema validation happens in the
    build pipeline (the same ``PackageManifest`` path the installer uses).
    """

    mode: str
    target: str  # <packageId>@<major>
    manifest: dict[str, Any]
    files: dict[str, bytes]
    base_digest: str | None = None  # required for extend, forbidden for create
    behavior_entries: tuple[str, ...] = ()
    dependencies: dict[str, dict[str, str]] = field(default_factory=dict)
    preview_templates: tuple[str, ...] = ()
    nodes: tuple[RequestedNode, ...] = ()
    timeout_class: str = "standard"
    contract_version: str = BUILD_CONTRACT_VERSION

    def manifest_template_ids(self) -> list[str]:
        return [
            t.get("id") for t in (self.manifest.get("templates") or [])
            if isinstance(t, dict) and isinstance(t.get("id"), str)
        ]


def _parse_target(raw: Mapping[str, Any]) -> str:
    target = raw.get("target")
    if not isinstance(target, str) or not PACKAGE_DIR_RE.match(target):
        raise BuildRequestError(
            f"target must be '<packageId>@<major>', got {target!r}"
        )
    return target


def _cross_check_manifest_coordinate(target: str, manifest: Mapping[str, Any]) -> None:
    package_id = manifest.get("id")
    major = (manifest.get("compatibility") or {}).get("major")
    if not isinstance(package_id, str) or not isinstance(major, int):
        raise BuildRequestError(
            "manifest must declare string 'id' and integer 'compatibility.major'"
        )
    expected = f"{package_id}@{major}"
    if expected != target:
        raise BuildRequestError(
            f"target {target!r} does not match manifest coordinate {expected!r}"
        )


def _parse_files(raw_files: Any) -> dict[str, bytes]:
    if raw_files is None:
        return {}
    if not isinstance(raw_files, dict):
        raise BuildRequestError("files must be an object of {path: entry}")
    if len(raw_files) > MAX_FILES:
        raise BuildRequestError(f"files exceeds the {MAX_FILES}-file limit")
    out: dict[str, bytes] = {}
    total = 0
    for path, entry in raw_files.items():
        if not isinstance(path, str) or len(path) > MAX_PATH_CHARS:
            raise BuildRequestError(
                f"file path must be a string of at most {MAX_PATH_CHARS} chars, "
                f"got {str(path)[:60]!r}"
            )
        segments = _safe_member_path(path)  # installer rules — one truth
        normalized = "/".join(segments)
        if normalized in ("manifest.json", "integrity.json"):
            raise BuildRequestError(
                f"{normalized} never rides the file map: the manifest is the "
                "typed 'manifest' field and integrity is generated by the builder"
            )
        if segments[0] == "scripts":
            raise BuildRequestError(
                "scripts/ is builder-owned (compiled behavior bundles); ship "
                "behavior SOURCE under sources/ and list it in behaviorEntries"
            )
        _check_allowed_layout(segments)
        if normalized in out:
            raise BuildRequestError(f"duplicate file path after normalization: {normalized!r}")
        if not isinstance(entry, dict) or not entry:
            raise BuildRequestError(
                f'files[{normalized!r}] must be {{"text": "..."}} or {{"base64": "..."}}'
            )
        unknown = set(entry) - _FILE_ENTRY_KEYS
        if unknown or len(entry) != 1:
            raise BuildRequestError(
                f"files[{normalized!r}] must carry exactly one of "
                f"{sorted(_FILE_ENTRY_KEYS)}, got {sorted(entry)}"
            )
        if "text" in entry:
            body = entry["text"]
            if not isinstance(body, str):
                raise BuildRequestError(f"files[{normalized!r}].text must be a string")
            data = body.encode("utf-8")
        else:
            b64 = entry["base64"]
            if not isinstance(b64, str):
                raise BuildRequestError(f"files[{normalized!r}].base64 must be a string")
            try:
                data = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise BuildRequestError(
                    f"files[{normalized!r}].base64 is not valid base64: {exc}"
                ) from exc
        if len(data) > MAX_FILE_BYTES:
            raise BuildRequestError(
                f"files[{normalized!r}] exceeds the per-file limit "
                f"({len(data)} > {MAX_FILE_BYTES} bytes)"
            )
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise BuildRequestError(
                f"files exceed the total size limit ({MAX_TOTAL_BYTES} bytes)"
            )
        out[normalized] = data
    return out


def _parse_behavior_entries(raw: Any, files: Mapping[str, bytes]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BuildRequestError("behaviorEntries must be a list of file paths")
    if len(raw) > MAX_BEHAVIOR_ENTRIES:
        raise BuildRequestError(
            f"behaviorEntries exceeds the {MAX_BEHAVIOR_ENTRIES}-entry limit"
        )
    entries: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise BuildRequestError("behaviorEntries items must be strings")
        if item in entries:
            raise BuildRequestError(f"duplicate behavior entry {item!r}")
        if not item.startswith("sources/"):
            raise BuildRequestError(
                f"behavior entry {item!r} must live under sources/"
            )
        if not item.endswith(_BEHAVIOR_ENTRY_SUFFIXES):
            raise BuildRequestError(
                f"behavior entry {item!r} must end in one of {list(_BEHAVIOR_ENTRY_SUFFIXES)}"
            )
        if item not in files:
            raise BuildRequestError(
                f"behavior entry {item!r} is not present in files"
            )
        entries.append(item)
    return tuple(entries)


def _parse_dependencies(raw: Any) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BuildRequestError("dependencies must be an object")
    unknown = set(raw) - set(_DEPENDENCY_ECOSYSTEMS)
    if unknown:
        raise BuildRequestError(
            f"dependencies has unknown ecosystems {sorted(unknown)}; "
            f"expected a subset of {list(_DEPENDENCY_ECOSYSTEMS)}"
        )
    out: dict[str, dict[str, str]] = {}
    for eco, entries in raw.items():
        if not isinstance(entries, dict):
            raise BuildRequestError(f"dependencies.{eco} must be an object of name: constraint")
        if len(entries) > MAX_DEPENDENCIES_PER_ECOSYSTEM:
            raise BuildRequestError(
                f"dependencies.{eco} exceeds the "
                f"{MAX_DEPENDENCIES_PER_ECOSYSTEM}-entry limit"
            )
        eco_out: dict[str, str] = {}
        for name, constraint in entries.items():
            if (not isinstance(name, str) or not name.strip()
                    or len(name) > MAX_DEPENDENCY_NAME_CHARS
                    or any(c.isspace() for c in name)):
                raise BuildRequestError(
                    f"dependencies.{eco} has invalid name {str(name)[:60]!r}"
                )
            if (not isinstance(constraint, str) or not constraint.strip()
                    or len(constraint) > MAX_DEPENDENCY_CONSTRAINT_CHARS):
                raise BuildRequestError(
                    f"dependencies.{eco}[{name!r}] constraint must be a "
                    "non-empty bounded string"
                )
            eco_out[name] = constraint
        out[eco] = eco_out
    return out


def _parse_preview_templates(raw: Any, manifest_ids: list[str]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BuildRequestError("previewTemplates must be a list of template ids")
    if len(raw) > MAX_PREVIEW_TEMPLATES:
        raise BuildRequestError(
            f"previewTemplates exceeds the {MAX_PREVIEW_TEMPLATES}-entry limit"
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not TEMPLATE_ID_RE.match(item):
            raise BuildRequestError(f"previewTemplates item {item!r} is not a template id")
        if item not in manifest_ids:
            raise BuildRequestError(
                f"previewTemplates item {item!r} is not declared by the draft manifest"
            )
        if item not in out:
            out.append(item)
    return tuple(out)


def _parse_appearance(raw: Any, where: str) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BuildRequestError(f"{where}.appearance must be an object")
    unknown = set(raw) - {"backgroundColor"}
    if unknown:
        raise BuildRequestError(
            f"{where}.appearance has unknown keys {sorted(unknown)}; "
            "only backgroundColor is supported"
        )
    color = raw.get("backgroundColor")
    if (not isinstance(color, str) or not color.strip()
            or len(color) > MAX_APPEARANCE_VALUE_CHARS
            or any(c in color for c in "\n\r\t")):
        raise BuildRequestError(
            f"{where}.appearance.backgroundColor must be a short single-line string"
        )
    return {"backgroundColor": color}


def _parse_nodes(raw: Any, *, mode: str, manifest_ids: list[str]) -> tuple[RequestedNode, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BuildRequestError("nodes must be a list of requested node objects")
    if len(raw) > MAX_REQUESTED_NODES:
        raise BuildRequestError(f"nodes exceeds the {MAX_REQUESTED_NODES}-node limit")
    out: list[RequestedNode] = []
    for i, item in enumerate(raw):
        where = f"nodes[{i}]"
        if not isinstance(item, dict):
            raise BuildRequestError(f"{where} must be an object")
        unknown = set(item) - _NODE_KEYS
        if unknown:
            raise BuildRequestError(f"{where} has unknown keys {sorted(unknown)}")
        template_id = item.get("templateId")
        if not isinstance(template_id, str) or not TEMPLATE_ID_RE.match(template_id):
            raise BuildRequestError(f"{where}.templateId {template_id!r} is not a template id")
        # In create mode the manifest is the complete template universe; in
        # extend mode a node may target a preserved base template — the merge
        # planner checks membership against the merged manifest instead.
        if mode == "create" and template_id not in manifest_ids:
            raise BuildRequestError(
                f"{where}.templateId {template_id!r} is not declared by the draft manifest"
            )
        title = item.get("title")
        if title is not None and (not isinstance(title, str) or len(title) > MAX_NODE_TITLE_CHARS):
            raise BuildRequestError(f"{where}.title must be a string of at most "
                                    f"{MAX_NODE_TITLE_CHARS} chars")
        goal = item.get("goal")
        if goal is not None and (not isinstance(goal, str) or len(goal) > MAX_NODE_GOAL_CHARS):
            raise BuildRequestError(f"{where}.goal must be a string of at most "
                                    f"{MAX_NODE_GOAL_CHARS} chars")
        content = item.get("content")
        if content is not None and (not isinstance(content, str)
                                    or len(content) > MAX_NODE_CONTENT_CHARS):
            raise BuildRequestError(f"{where}.content must be a string of at most "
                                    f"{MAX_NODE_CONTENT_CHARS} chars")
        out.append(RequestedNode(
            template_id=template_id,
            title=title,
            content=content,
            goal=goal,
            appearance=_parse_appearance(item.get("appearance"), where),
        ))
    return tuple(out)


def parse_build_request(raw: Any) -> PackageBuildRequest:
    """Validate an untrusted request payload into a :class:`PackageBuildRequest`.

    Fail-closed and loud: unknown keys, malformed values, and out-of-policy
    sizes all raise :class:`BuildRequestError` with the offending field named.
    """
    if not isinstance(raw, dict):
        raise BuildRequestError("build request must be an object")
    unknown = set(raw) - _REQUEST_KEYS
    if unknown:
        raise BuildRequestError(f"build request has unknown keys {sorted(unknown)}")

    contract = raw.get("contractVersion", BUILD_CONTRACT_VERSION)
    if contract != BUILD_CONTRACT_VERSION:
        raise BuildRequestError(
            f"unsupported contractVersion {contract!r}; this builder speaks "
            f"{BUILD_CONTRACT_VERSION!r}"
        )

    mode = raw.get("mode")
    if mode not in _MODES:
        raise BuildRequestError(f"mode must be one of {list(_MODES)}, got {mode!r}")

    target = _parse_target(raw)
    manifest = raw.get("manifest")
    if not isinstance(manifest, dict):
        raise BuildRequestError("manifest is required and must be an object")
    _cross_check_manifest_coordinate(target, manifest)

    base_digest = raw.get("baseDigest")
    if mode == "extend":
        if not isinstance(base_digest, str) or not _DIGEST_RE.match(base_digest):
            raise BuildRequestError(
                "extend requests must pin baseDigest (64 lowercase hex chars) "
                "to the installed target's digest"
            )
    elif base_digest is not None:
        raise BuildRequestError("create requests must not carry baseDigest")

    timeout_class = raw.get("timeoutClass", "standard")
    if timeout_class not in _TIMEOUT_CLASSES:
        raise BuildRequestError(
            f"timeoutClass must be one of {list(_TIMEOUT_CLASSES)}, got {timeout_class!r}"
        )

    files = _parse_files(raw.get("files"))
    manifest_ids = [
        t.get("id") for t in (manifest.get("templates") or [])
        if isinstance(t, dict) and isinstance(t.get("id"), str)
    ]
    return PackageBuildRequest(
        mode=mode,
        target=target,
        manifest=manifest,
        files=files,
        base_digest=base_digest if mode == "extend" else None,
        behavior_entries=_parse_behavior_entries(raw.get("behaviorEntries"), files),
        dependencies=_parse_dependencies(raw.get("dependencies")),
        preview_templates=_parse_preview_templates(raw.get("previewTemplates"), manifest_ids),
        nodes=_parse_nodes(raw.get("nodes"), mode=mode, manifest_ids=manifest_ids),
        timeout_class=timeout_class,
        contract_version=BUILD_CONTRACT_VERSION,
    )


def canonical_request_payload(request: PackageBuildRequest) -> dict[str, Any]:
    """A JSON-safe normalized view of *request* — file bodies content-addressed
    by their own SHA-256 so the payload stays compact and deterministic."""
    return {
        "contractVersion": request.contract_version,
        "mode": request.mode,
        "target": request.target,
        "baseDigest": request.base_digest,
        "manifest": request.manifest,
        "files": {
            path: hashlib.sha256(body).hexdigest()
            for path, body in sorted(request.files.items())
        },
        "behaviorEntries": list(request.behavior_entries),
        "dependencies": request.dependencies,
        "previewTemplates": list(request.preview_templates),
        "nodes": [n.to_payload() for n in request.nodes],
        "timeoutClass": request.timeout_class,
    }


def request_digest(request: PackageBuildRequest) -> str:
    """SHA-256 of the normalized request — the build's identity (dev/89 §3.1):
    identical requests are identical builds, so retries are idempotent and
    successful results cacheable by this digest."""
    canonical = json.dumps(
        canonical_request_payload(request),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PackageBuildResult:
    """The authenticated description of one finished build (dev/89 §3.8).

    A ``ready`` result names the exact staged artifact by digest; the review
    proposal references that digest and Apply promotes only it — the result
    never carries mutable filesystem paths or model-supplied hashes.
    """

    status: str  # "ready" | "failed"
    input_digest: str
    base_digest: str | None = None
    artifact_digest: str | None = None  # required when ready
    builder_version: str = ""
    diff: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    policy_findings: tuple[str, ...] = ()
    preview: dict[str, Any] | None = None
    archive_size: int = 0
    warnings: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()
    contract_version: str = BUILD_CONTRACT_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "status": self.status,
            "inputDigest": self.input_digest,
            "baseDigest": self.base_digest,
            "artifactDigest": self.artifact_digest,
            "builderVersion": self.builder_version,
            "diff": self.diff,
            "dependencies": self.dependencies,
            "policyFindings": list(self.policy_findings),
            "preview": self.preview,
            "archiveSize": self.archive_size,
            "warnings": list(self.warnings),
            "logs": list(self.logs),
        }


def parse_build_result(raw: Any) -> PackageBuildResult:
    """Round-trip validation for a stored/transported result payload."""
    if not isinstance(raw, dict):
        raise BuildRequestError("build result must be an object")
    status = raw.get("status")
    if status not in _RESULT_STATUSES:
        raise BuildRequestError(
            f"result status must be one of {list(_RESULT_STATUSES)}, got {status!r}"
        )
    input_digest = raw.get("inputDigest")
    if not isinstance(input_digest, str) or not _DIGEST_RE.match(input_digest):
        raise BuildRequestError("result inputDigest must be 64 lowercase hex chars")
    artifact_digest = raw.get("artifactDigest")
    if status == "ready":
        if not isinstance(artifact_digest, str) or not _DIGEST_RE.match(artifact_digest):
            raise BuildRequestError("a ready result must carry a valid artifactDigest")
    elif artifact_digest is not None:
        raise BuildRequestError("a failed result must not carry an artifactDigest")
    base_digest = raw.get("baseDigest")
    if base_digest is not None and (
            not isinstance(base_digest, str) or not _DIGEST_RE.match(base_digest)):
        raise BuildRequestError("result baseDigest must be 64 lowercase hex chars when present")
    archive_size = raw.get("archiveSize", 0)
    if not isinstance(archive_size, int) or archive_size < 0:
        raise BuildRequestError("result archiveSize must be a non-negative integer")

    def _str_tuple(key: str) -> tuple[str, ...]:
        value = raw.get(key) or []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise BuildRequestError(f"result {key} must be a list of strings")
        return tuple(value)

    diff = raw.get("diff") or {}
    dependencies = raw.get("dependencies") or {}
    preview = raw.get("preview")
    if not isinstance(diff, dict) or not isinstance(dependencies, dict):
        raise BuildRequestError("result diff and dependencies must be objects")
    if preview is not None and not isinstance(preview, dict):
        raise BuildRequestError("result preview must be an object when present")
    builder_version = raw.get("builderVersion", "")
    if not isinstance(builder_version, str):
        raise BuildRequestError("result builderVersion must be a string")
    return PackageBuildResult(
        status=status,
        input_digest=input_digest,
        base_digest=base_digest,
        artifact_digest=artifact_digest if status == "ready" else None,
        builder_version=builder_version,
        diff=diff,
        dependencies=dependencies,
        policy_findings=_str_tuple("policyFindings"),
        preview=preview,
        archive_size=archive_size,
        warnings=_str_tuple("warnings"),
        logs=_str_tuple("logs"),
        contract_version=BUILD_CONTRACT_VERSION,
    )
