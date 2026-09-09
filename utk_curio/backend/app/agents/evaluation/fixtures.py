"""Prompt fixtures: load, validate, digest (memo dev/121).

A fixture pairs one natural-language prompt with one shipped example dataflow
and its answer key. Two rules make it trustworthy, and both are enforced here
rather than trusted:

*Drift.* ``source.sha256`` must equal the digest of the example on disk. An
example edit fails the unit suite until a person re-reviews the fixture --
the expected graph is not silently re-derived under a changed example.

*No leak.* The evaluated model receives ``prompt`` (and ``context``) and
nothing else, so those two strings must carry no node id, no canonical
template id, no line of node content, no plan-grammar token and no JSON
object. :func:`leak_findings` is the check, and it runs in the unit suite over
every committed fixture.

The loader never writes and never repairs: a fixture that disagrees with its
example is an error to report, not a file to fix.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

#: ``<repo>/utk_curio/backend/app/agents/evaluation/fixtures.py`` -> ``<repo>``
_REPO_ROOT = Path(__file__).resolve().parents[5]

FIXTURE_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "example-prompt-fixture.v1.json"
FIXTURE_ROOT = _REPO_ROOT / "docs" / "examples" / "prompts"
EXAMPLES_ROOT = _REPO_ROOT / "docs" / "examples"

#: The curated corpus and the legacy corpus, in the shape the existing suites
#: enumerate them (``test_examples.py`` and ``test_trill_schema.py``).
CURATED_GLOB = "[0-9][0-9]-*.json"
LEGACY_GLOB = "dataflows/*.json"

_PLAN_TOKENS = ("dataflowPlan", "curio.v1", "toolRequest", "delegateRequest")
_CONTENT_LINE_MIN = 25


class FixtureError(Exception):
    """A fixture is unreadable, invalid, or disagrees with its example."""


@dataclass(frozen=True)
class Fixture:
    """One loaded fixture plus the paths behind it."""

    path: Path
    data: dict

    @property
    def fixture_id(self) -> str:
        return str(self.data.get("fixtureId") or "")

    @property
    def prompt(self) -> str:
        return str(self.data.get("prompt") or "")

    @property
    def context(self) -> str | None:
        value = self.data.get("context")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def source_path(self) -> Path:
        return _REPO_ROOT / str(self.data.get("source", {}).get("path") or "")

    @property
    def source_sha256(self) -> str:
        return str(self.data.get("source", {}).get("sha256") or "")

    @property
    def expected(self) -> dict:
        return dict(self.data.get("expected") or {})

    @property
    def required(self) -> dict:
        required = dict(self.data.get("required") or {})
        required.setdefault("datasets", [])
        required.setdefault("packages", [])
        required.setdefault("paths", [])
        return required

    @property
    def intents(self) -> list:
        return list(self.data.get("intents") or [])

    @property
    def capability(self) -> dict:
        return dict(self.data.get("capability") or {})

    @property
    def needs(self) -> tuple:
        return tuple(self.capability.get("needs") or ())

    @property
    def tier(self) -> str:
        return str(self.capability.get("tier") or "T0")

    @property
    def thresholds(self) -> dict:
        return dict(self.data.get("thresholds") or {"pass": 1.0})

    @property
    def execution(self) -> dict:
        execution = dict(self.data.get("execution") or {})
        execution.setdefault("mode", "none")
        execution.setdefault("browserOnlyKinds", [])
        return execution

    @property
    def split(self) -> str:
        return str(self.data.get("split") or "validation")

    @property
    def review_status(self) -> str:
        return str((self.data.get("review") or {}).get("status") or "pending-owner-review")

    @property
    def approved(self) -> bool:
        return self.review_status == "approved"

    def prompt_sha256(self) -> str:
        payload = self.prompt + ("\n" + self.context if self.context else "")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def fixture_sha256(self) -> str:
        return sha256_of_file(self.path)

    def skips_for(self, *, scope: str, active: Iterable) -> list:
        """The fixture's own skip entries that apply, given the active
        conditions (env flags the runner set, plus this fixture's needs).

        Every exclusion is data in the fixture with a written reason -- there is
        no place in the harness where a case is dropped silently.
        """
        active_set = {str(a) for a in active}
        out = []
        for entry in self.capability.get("skip") or []:
            if not isinstance(entry, Mapping):
                continue
            entry_scope = str(entry.get("scope") or "execution")
            if entry_scope not in (scope, "all"):
                continue
            if str(entry.get("when") or "") in active_set:
                out.append(dict(entry))
        return out


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema() -> dict:
    return json.loads(FIXTURE_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_fixture_dict(data: Mapping, *, where: str = "<fixture>") -> None:
    """Schema-validate one fixture. Raises :class:`FixtureError` with every
    message, so a broken fixture reports all of its problems at once."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - jsonschema is a test dep
        raise FixtureError("jsonschema is required to validate fixtures") from exc
    validator = Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(dict(data)), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise FixtureError(f"{where} is not a valid example-prompt-fixture.v1: {detail}")


def load_fixture(path: Path, *, validate: bool = True) -> Fixture:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FixtureError(f"{path}: unreadable fixture ({exc})") from exc
    if not isinstance(data, dict):
        raise FixtureError(f"{path}: a fixture must be a JSON object")
    if validate:
        validate_fixture_dict(data, where=str(path))
    return Fixture(path=Path(path), data=data)


def fixture_paths(root: Path | None = None) -> list:
    """Every committed fixture, curated then legacy, sorted."""
    base = Path(root or FIXTURE_ROOT)
    curated = sorted(base.glob("*.prompt.json"))
    legacy = sorted((base / "dataflows").glob("*.prompt.json"))
    return curated + legacy


def load_fixtures(root: Path | None = None, *, validate: bool = True) -> list:
    return [load_fixture(p, validate=validate) for p in fixture_paths(root)]


def example_paths(root: Path | None = None) -> list:
    """The corpus this harness must cover: 11 curated + 20 legacy."""
    base = Path(root or EXAMPLES_ROOT)
    return sorted(base.glob(CURATED_GLOB)) + sorted(base.glob(LEGACY_GLOB))


def fixture_id_for_example(path: Path) -> str:
    """``01-vega-lite-chained-transforms`` / ``Interaction_Vega`` -- the stem."""
    return Path(path).stem


def digest_matches(fixture: Fixture) -> bool:
    try:
        return sha256_of_file(fixture.source_path) == fixture.source_sha256
    except OSError:
        return False


def leak_findings(fixture: Fixture, example: Mapping) -> list:
    """Everything in the prompt that would give the answer away.

    Empty list means the prompt is safe to send. Human node-kind names ("Data
    Transformation", "Vega-Lite") are deliberately NOT findings: the
    walkthroughs use them and so would a user describing their goal. What is
    forbidden is the implementation -- ids, canonical template ids, code, and
    the plan grammar.
    """
    inner = example.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else example
    text = fixture.prompt + ("\n" + (fixture.context or ""))
    findings: list = []

    for node in dataflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("id") or "")
        if len(node_id) >= 4 and node_id in text:
            findings.append(f"node id {node_id!r} appears in the prompt")
        node_type = str(node.get("type") or "")
        if "/" in node_type and node_type.split("@")[0] in text:
            findings.append(f"canonical template id {node_type!r} appears in the prompt")
        content = node.get("content")
        if isinstance(content, str):
            for line in content.splitlines():
                stripped = line.strip()
                if len(stripped) >= _CONTENT_LINE_MIN and stripped in text:
                    findings.append(f"node content line {stripped[:48]!r} appears in the prompt")
                    break
    for edge in dataflow.get("edges") or []:
        if isinstance(edge, Mapping):
            edge_id = str(edge.get("id") or "")
            if len(edge_id) >= 8 and edge_id in text:
                findings.append(f"edge id {edge_id[:32]!r} appears in the prompt")

    for token in _PLAN_TOKENS:
        if token in text:
            findings.append(f"plan-grammar token {token!r} appears in the prompt")
    if re.search(r"\{\s*\"[A-Za-z_]", text):
        findings.append("the prompt contains a JSON object")
    if "```" in text:
        findings.append("the prompt contains a fenced code block")
    return findings
