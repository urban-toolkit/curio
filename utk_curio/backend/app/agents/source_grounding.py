"""Source grounding for agent-authored node content (memo dev/114, DEC-072).

The ONE gate every agent-authored node content passes before it can become a
proposal or be written by Solve. Issue #298: the Node Builder proposed
``pd.read_csv("bras_ibge_data.csv")`` — a file that never existed — because
nothing between "load this data" and the review card resolved, verified, or
checked the source. DEC-053 already made "the runtime verifies, never the
model" the rule for the Dataset Finder's candidate rows; this module extends
the same rule to the code that consumes them.

The rules (all runtime-enforced; prompt wording only teaches them):

- a **local path** is grounded only when the user typed it in this
  conversation or the Data Catalog resolved it (an installed dataset's real
  path — the same truth ``catalog.search`` serves); the portable
  ``curio_dataset_path("<id>")`` call the loader recipe emits is grounded
  when the id is a dataset of this project's catalog;
- a **URL** is grounded only when the runtime probed it this run (the dev/67-4
  gate: ``verified``, or ``401``/``403`` = the endpoint exists behind a
  credential) or an already-verified candidate row in this session carries
  it — a URL in the user's text is NOT evidence (the DEC-047 handoff prompt
  is model-suggested text the user forwards);
- a **data-loading node with no source** is grounded only when the USER asked
  for synthetic data (or the model declared ``synthetic: true`` for such a
  request) and is labeled synthetic — inline invented values are the same
  fabrication class as an invented filename;
- anything else is **refused with the correction named** — never proposed,
  never written, never described as existing.

Pure by construction: no Flask, no provider, no store. The catalog read, the
session read, and the egress-budgeted probe are supplied by the caller
through :class:`GroundingContext`, so the same verdict runs at every boundary
(node.create, node.insert, node.content.write, the dev/73 runtime review
mint, Solve, plan-carried content, node.template.create).
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

# File extensions that make a string literal read as a data file. Deliberately
# a data-file list, not "anything with a dot": column names, format strings,
# and module paths must never be mistaken for sources.
DATA_EXTENSIONS: tuple[str, ...] = (
    ".csv", ".tsv", ".json", ".geojson", ".topojson", ".shp", ".gpkg",
    ".parquet", ".feather", ".tif", ".tiff", ".xlsx", ".xls", ".nc",
    ".zip", ".gz", ".pbf", ".kml", ".kmz", ".gml", ".las", ".laz",
)

# Words that, in the USER's own text, mean "I want made-up data". The model's
# text never counts — it may not authorize itself.
SYNTHETIC_MARKERS: tuple[str, ...] = (
    "synthetic", "fake data", "mock data", "dummy data", "sample data",
    "made-up", "made up data", "fabricated", "simulated data", "random data",
    "generate data", "generate some data", "toy data", "placeholder data",
    "invent some data", "example data",
)

#: Bounds — a source list is display metadata, never a document.
MAX_REFS = 32
_VALUE_MAX_CHARS = 300  # the candidate URL bound (content._CANDIDATE_URL_MAX_CHARS)
_LABEL_MAX_CHARS = 200
_TITLE_MAX_CHARS = 120

_URL_SCHEMES = ("http://", "https://")
# The portable catalog reference the datasets domain's loader recipe emits and
# the sandbox resolves at run time (KEEP IN SYNC with _DATASET_PATH_CALL_RE in
# backend/app/api/routes.py and the frontend datasetLoaderSnippets.ts).
DATASET_PATH_CALL_RE = re.compile(
    r"""curio_dataset_path\(\s*(["'])([A-Za-z0-9][A-Za-z0-9._@-]{0,199})\1\s*\)"""
)
# dev/116 (DEC-074): connection keys. The call shape is owned by
# users/connection_keys (ONE regex); a credential-shaped literal is what the
# gate refuses so a pasted key never executes, never reaches the journal and
# never lands in a proposal.
from utk_curio.backend.app.users.connection_keys import (  # noqa: E402
    SECRET_CALL_RE,
    secret_names as _secret_names,
)

# KEEP IN SYNC with the editor's twin (dev/117):
# frontend/urban-workflows/src/services/connectionKeys/credentialLiterals.ts —
# both sides assert the same fixture list (test_source_grounding.py ↔
# credentialLiterals.test.ts).
_CRED_NAME_RE = re.compile(
    r"^(?:api[_-]?key|apikey|key|token|access[_-]?token|secret|api[_-]?secret|"
    r"password|passwd|auth(?:orization)?|bearer|client[_-]?secret|x[_-]api[_-]key)$",
    re.IGNORECASE,
)
#: A value that looks like a credential: long, one token, no spaces — and not
#: a URL or a path (those are sources, judged by the other rules).
_CRED_VALUE_RE = re.compile(r"^(?:Bearer\s+)?[A-Za-z0-9_\-.~+/=]{20,}$")
_CRED_LITERAL_FALLBACK_RE = re.compile(
    r"""(?P<name>api[_-]?key|apikey|key|token|access[_-]?token|secret|password|authorization|x-api-key)"""
    r"""["']?\s*[:=]\s*["'](?P<value>(?:Bearer\s+)?[A-Za-z0-9_\-.~+/=]{20,})["']""",
    re.IGNORECASE,
)

_STRING_LITERAL_RE = re.compile(
    r"""(?P<q>['"])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.DOTALL
)
_TOKEN_SPLIT_RE = re.compile(r"""[\s"'`<>()\[\]{},;]+""")
_TRAILING_PUNCT = ".,;:!?"


@dataclass(frozen=True)
class SourceRef:
    """One source-shaped literal found in code."""

    kind: str  # "path" | "url" | "catalog-id"
    literal: str
    line: int
    partial: bool = False  # the constant prefix of an f-string


@dataclass(frozen=True)
class CatalogRef:
    """An installed Data Catalog dataset the runtime resolved to a real path."""

    dataset_id: str
    title: str
    format: str
    path: str


@dataclass(frozen=True)
class SecretRef:
    """A saved connection key as the gate and the delegate see it: the name
    code uses, the host it is for, how the API expects it — never the value."""

    name: str
    host: str
    delivery: str = "code"

    @property
    def use_line(self) -> str:
        return f'api_key = curio_secret("{self.name}")'


@dataclass
class GroundingContext:
    """Everything the verdict needs, supplied by the caller."""

    catalog_paths: dict[str, CatalogRef] = field(default_factory=dict)
    #: dataset id → ref, for the portable ``curio_dataset_path("<id>")`` form.
    catalog_ids: dict[str, CatalogRef] = field(default_factory=dict)
    user_paths: set[str] = field(default_factory=set)
    verified_urls: dict[str, dict] = field(default_factory=dict)
    synthetic_requested: bool = False
    is_data_loading: bool = False
    #: The run-budgeted DEC-053 prober (``verify.verify_external_source``
    #: behind a per-run budget + cache), or None when no probe is possible.
    probe: Callable[[str], dict] | None = None
    #: Grant-aware corrective routes to name in a refusal (DEC-067): each is
    #: named ONLY when the refusing run can actually take it.
    hints: list[str] = field(default_factory=list)
    #: dev/116: the user's saved connection keys, by name — refs only.
    secrets: dict[str, SecretRef] = field(default_factory=dict)
    #: dev/116: resolves names → values for a keyed probe (the ONE reader of
    #: values on the agent path); None when no store is reachable.
    secret_values: Callable[[list[str]], dict] | None = None


@dataclass
class GroundingVerdict:
    ok: bool
    violations: list[str] = field(default_factory=list)
    #: The proposal ``source`` payload (None when nothing is worth stating —
    #: a non-data-loading node that opens no file).
    source: dict | None = None
    refs: list[SourceRef] = field(default_factory=list)


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------


def classify_literal(text: object) -> str | None:
    """``"url"``, ``"path"``, or None for a string that is not a source."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value or len(value) > _VALUE_MAX_CHARS:
        return None
    lowered = value.lower()
    if lowered.startswith(_URL_SCHEMES):
        return "url"
    if any(ch in value for ch in "\n\r\t"):
        return None
    if " " in value and "/" not in value and "\\" not in value:
        return None  # a sentence, not a filename
    if lowered.endswith(DATA_EXTENSIONS):
        return "path"
    # A rooted or nested path with a dotted file name — any extension — still
    # names a file on disk the code will try to open. A single
    # ``package/module.py``-shaped segment pair is left alone (an identifier,
    # not a data file).
    has_sep = "/" in value or "\\" in value
    dotted_tail = bool(re.search(r"[^/\\]+\.[A-Za-z0-9]{1,5}$", value))
    if has_sep and dotted_tail:
        rooted = value.startswith(("/", "./", "../", "~")) or bool(
            re.match(r"^[A-Za-z]:[\\/]", value)
        )
        nested = (value.count("/") + value.count("\\")) >= 2
        if rooted or nested:
            return "path"
    return None


def _joined_str_parts(node: ast.JoinedStr) -> tuple[str, str, bool]:
    """``(constant_prefix, template, dynamic)`` for an f-string: the leading
    constant text, the whole string with every placeholder rendered as
    ``{…}``, and whether any placeholder exists at all."""
    prefix_parts: list[str] = []
    template_parts: list[str] = []
    dynamic = False
    still_prefix = True
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            template_parts.append(value.value)
            if still_prefix:
                prefix_parts.append(value.value)
        else:
            dynamic = True
            still_prefix = False
            template_parts.append("{…}")
    return "".join(prefix_parts), "".join(template_parts), dynamic


def _parse_python(code: str) -> tuple[ast.AST, int] | None:
    """Parse node content. Curio node code is a function BODY (a top-level
    ``return df`` is legal there and a SyntaxError to ``ast.parse``), so a
    failed bare parse retries wrapped in a def; the returned offset corrects
    line numbers back to the content's own."""
    try:
        return ast.parse(code), 0
    except (SyntaxError, ValueError):
        pass
    import textwrap

    wrapped = "def __curio_node__():\n" + textwrap.indent(code, "    ")
    try:
        return ast.parse(wrapped), 1
    except (SyntaxError, ValueError):
        return None


#: The value of a ``"$schema"`` key is the document's own format declaration —
#: vega-lite's ``https://vega.github.io/schema/vega-lite/v6.json``, and the
#: equivalent in any other JSON document a grammar node holds. It is not data
#: the node loads, so grounding it proves nothing, and probing it is a request
#: to a third party on every document the agent writes. Worse, it fails CLOSED:
#: an install with no route to vega.github.io could not write a Vega document
#: at all, because one unverifiable URL refuses the whole candidate.
#:
#: Keyed on the KEY, in both scanners, so this is a rule about what a `$schema`
#: value IS — not a list of schema hosts to trust.
SCHEMA_DECLARATION_KEY = "$schema"
_SCHEMA_KEY_RE = re.compile(r'"\$schema"\s*:\s*$')


def _scan_python(code: str) -> list[SourceRef] | None:
    parsed = _parse_python(code)
    if parsed is None:
        return None
    tree, offset = parsed
    refs: list[SourceRef] = []
    # Constant children of an f-string are scanned through the f-string —
    # never a second time as bare constants; the id inside a
    # ``curio_dataset_path("<id>")`` call is a catalog reference, not a path.
    fstring_children: set[int] = set()
    call_ids: set[int] = set()
    schema_values: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            # A grammar document parses as a dict literal, so it reaches the
            # AST scanner rather than the regex one; see SCHEMA_DECLARATION_KEY.
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == SCHEMA_DECLARATION_KEY
                    and isinstance(value, ast.Constant)
                ):
                    schema_values.add(id(value))
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if child is not node:
                    fstring_children.add(id(child))
        elif isinstance(node, ast.Call) and _is_dataset_path_call(node):
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                call_ids.add(id(arg))
                refs.append(SourceRef(
                    "catalog-id", arg.value.strip(), max(1, getattr(node, "lineno", 1) - offset)
                ))
    for node in ast.walk(tree):
        line = max(1, getattr(node, "lineno", 1) - offset)
        if isinstance(node, ast.JoinedStr):
            prefix, template, dynamic = _joined_str_parts(node)
            if not dynamic:
                kind = classify_literal(template)
                if kind:
                    refs.append(SourceRef(kind, template.strip(), line))
                continue
            if classify_literal(prefix) == "url":
                # ``f"https://host/path/{year}"`` — the constant prefix is the
                # probeable part; the rest is the request the node composes.
                refs.append(SourceRef("url", prefix.strip(), line, partial=True))
            elif classify_literal(template) in ("path", "url"):
                # ``f"{dir}/file.csv"`` — the file name is composed at run
                # time from a prefix the runtime cannot resolve: a partial ref
                # is refused with the correction named.
                refs.append(SourceRef("path", template.strip(), line, partial=True))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                id(node) in fstring_children
                or id(node) in call_ids
                or id(node) in schema_values
            ):
                continue
            kind = classify_literal(node.value)
            if kind:
                refs.append(SourceRef(kind, node.value.strip(), line))
    return refs


def _is_dataset_path_call(node: ast.Call) -> bool:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    return name == "curio_dataset_path"


def _scan_regex(code: str) -> list[SourceRef]:
    refs: list[SourceRef] = []
    call_spans: list[tuple[int, int]] = []
    for match in DATASET_PATH_CALL_RE.finditer(code):
        call_spans.append(match.span())
        refs.append(SourceRef("catalog-id", match.group(2), code.count("\n", 0, match.start()) + 1))
    for match in _STRING_LITERAL_RE.finditer(code):
        if any(a <= match.start() < b for a, b in call_spans):
            continue
        # Keyed on the KEY, not on the host: any document's own `$schema`, not
        # a list of schema sites to trust.
        if _SCHEMA_KEY_RE.search(code, 0, match.start()):
            continue
        body = match.group("body")
        kind = classify_literal(body)
        if kind:
            line = code.count("\n", 0, match.start()) + 1
            refs.append(SourceRef(kind, body.strip(), line))
    return refs


def scan_sources(code: object, engine: str | None = "python") -> list[SourceRef]:
    """Every source-shaped string literal in *code*, in order, bounded.

    Python content is walked with :mod:`ast` (string constants and the
    constant prefix of f-strings); a syntax error — or a non-python engine —
    falls back to a regex over quoted literals with the same classifier.
    """
    if not isinstance(code, str) or not code.strip():
        return []
    refs: list[SourceRef] | None = None
    if (engine or "python") == "python":
        refs = _scan_python(code)
    if refs is None:
        refs = _scan_regex(code)
    seen: set[tuple[str, str]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.kind, ref.literal)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
        if len(unique) >= MAX_REFS:
            break
    return unique


MAX_COMPOSED_REQUESTS = 4
_REQUEST_METHODS = ("get", "request")


def _const_value(node: ast.AST):
    """A JSON-ish constant (str/int/float/bool) or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
        return node.value
    return None


#: dev/116 live fix (2026-09-09): a ``curio_secret("<name>")`` used as a
#: request parameter is composable — as a PLACEHOLDER. The composed URL carries
#: it; the keyed probe swaps the saved value in (never the bare probe, never the
#: display). ``<``/``:``/``>`` survive urlencode as %3C/%3A/%3E.
SECRET_SENTINEL = "<curio_secret:{name}>"
_SENTINEL_RE = re.compile(r"^<curio_secret:([a-z0-9][a-z0-9_-]{0,39})>$")
_ENCODED_SENTINEL_RE = re.compile(r"%3Ccurio_secret%3A([a-z0-9][a-z0-9_-]{0,39})%3E")


def _secret_call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    if name != "curio_secret" or not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and SECRET_CALL_RE.match(
        f'curio_secret("{arg.value}")'
    ):
        return arg.value
    return None


def _dict_literal(node: ast.AST, names: dict | None = None) -> dict | None:
    if not isinstance(node, ast.Dict):
        return None
    out: dict = {}
    for key, value in zip(node.keys, node.values):
        k = _const_value(key) if key is not None else None
        v = _const_value(value)
        if v is None:
            secret = _secret_call_name(value)
            if secret is not None:
                v = SECRET_SENTINEL.format(name=secret)
            elif isinstance(value, ast.Name) and names and _SENTINEL_RE.match(str(names.get(value.id, ""))):
                v = names[value.id]
        if k is None or v is None:
            return None  # a computed key/value: the request is not composable here
        out[str(k)] = v
    return out


def split_secret_params(url: str) -> tuple[str, dict[str, str]]:
    """``(url without the placeholder parameters, {param: secret name})`` for a
    composed URL. Everything else in the query string stays as it was."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    keep: list[tuple[str, str]] = []
    secrets: dict[str, str] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        match = _SENTINEL_RE.match(value)
        if match:
            secrets[key] = match.group(1)
        else:
            keep.append((key, value))
    if not secrets:
        return url, {}
    bare = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment))
    return bare, secrets


def display_composed_url(url: str) -> str:
    """The composed URL for people: the placeholder reads as the call it was."""
    return _ENCODED_SENTINEL_RE.sub(lambda m: f'curio_secret("{m.group(1)}")', url)


def composed_requests(code: object) -> list[str]:
    """dev/115 field fix (2026-09-08): the requests a loader actually MAKES —
    ``requests.get(url, params={...})`` with the URL and the params both
    literal (directly or through a name bound once to a literal) — composed
    into the URL the server saw, in order, bounded and deduplicated.

    The base URL of a parameterised API almost always answers 200 while the
    composed request is what fails (the Census API redirects a key-less query
    to an HTML "Missing Key" page); probing the composed request is the
    evidence a correction needs. Anything dynamic is skipped — a guess is
    never composed."""
    if not isinstance(code, str) or not code.strip():
        return []
    parsed = _parse_python(code)
    if parsed is None:
        return []
    tree, _offset = parsed
    strings: dict[str, str] = {}
    dicts: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            strings.setdefault(name, node.value.value)
        elif isinstance(node.value, ast.JoinedStr):
            _prefix, template, dynamic = _joined_str_parts(node.value)
            if not dynamic:
                strings.setdefault(name, template)
        elif _secret_call_name(node.value) is not None:
            # ``api_key = curio_secret("census")`` — a placeholder the request
            # composer carries by name.
            strings.setdefault(name, SECRET_SENTINEL.format(name=_secret_call_name(node.value)))
        else:
            literal = _dict_literal(node.value, strings)
            if literal is not None:
                dicts.setdefault(name, literal)

    def _string_of(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return strings.get(node.id)
        return None

    def _dict_of(node: ast.AST | None) -> dict | None:
        if node is None:
            return None
        literal = _dict_literal(node, strings)
        if literal is not None:
            return literal
        if isinstance(node, ast.Name):
            return dicts.get(node.id)
        return None

    from urllib.parse import urlencode

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _REQUEST_METHODS:
            continue
        positional = list(node.args)
        if node.func.attr == "request":
            positional = positional[1:]  # ("GET", url, ...)
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        url = _string_of(positional[0] if positional else keywords.get("url"))
        params = _dict_of(keywords.get("params"))
        if not url or params is None or classify_literal(url) != "url":
            continue
        composed = url.strip() + ("&" if "?" in url else "?") + urlencode(params)
        if composed not in out:
            out.append(composed)
        if len(out) >= MAX_COMPOSED_REQUESTS:
            break
    return out


def secret_calls(code: object) -> list[tuple[str, int]]:
    """``(name, line)`` for every literal ``curio_secret("<name>")`` call."""
    if not isinstance(code, str) or "curio_secret" not in code:
        return []
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for match in SECRET_CALL_RE.finditer(code):
        name = match.group(2)
        if name in seen:
            continue
        seen.add(name)
        out.append((name, code.count("\n", 0, match.start()) + 1))
    return out


def secret_names(code: object) -> list[str]:
    return _secret_names(code)


def _is_credential_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_CRED_VALUE_RE.match(value.strip()))
        and classify_literal(value) is None
    )


def credential_literals(code: object, engine: str | None = "python") -> list[tuple[str, int]]:
    """``(name, line)`` for every credential-shaped literal: a long single
    token assigned to, keyed by, or passed as a name like ``api_key``,
    ``token``, ``Authorization``. The value itself is never returned."""
    if not isinstance(code, str) or not code.strip():
        return []
    found: list[tuple[str, int]] = []
    parsed = _parse_python(code) if (engine or "python") == "python" else None
    if parsed is not None:
        tree, offset = parsed
        for node in ast.walk(tree):
            line = max(1, getattr(node, "lineno", 1) - offset)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Name) and _CRED_NAME_RE.match(target.id)
                            and isinstance(node.value, ast.Constant)
                            and _is_credential_value(node.value.value)):
                        found.append((target.id, line))
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                            and _CRED_NAME_RE.match(key.value)
                            and isinstance(value, ast.Constant)
                            and _is_credential_value(value.value)):
                        found.append((key.value, line))
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg and _CRED_NAME_RE.match(kw.arg)
                            and isinstance(kw.value, ast.Constant)
                            and _is_credential_value(kw.value.value)):
                        found.append((kw.arg, line))
    else:
        for match in _CRED_LITERAL_FALLBACK_RE.finditer(code):
            if _is_credential_value(match.group("value")):
                found.append((match.group("name"), code.count("\n", 0, match.start()) + 1))
    unique: list[tuple[str, int]] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique[:MAX_REFS]


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def secret_for_host(ctx: "GroundingContext", url: str) -> "SecretRef | None":
    """The saved key bound to *url*'s host, if any."""
    host = _host_of(url)
    if not host:
        return None
    for ref in (ctx.secrets or {}).values():
        if ref.host == host:
            return ref
    return None


# --------------------------------------------------------------------------
# Context helpers (pure over texts the caller gathered)
# --------------------------------------------------------------------------


def path_literals(text: object) -> set[str]:
    """Path-shaped tokens in free text (the user's own messages)."""
    if not isinstance(text, str) or not text:
        return set()
    out: set[str] = set()
    for token in _TOKEN_SPLIT_RE.split(text):
        candidate = token.strip().rstrip(_TRAILING_PUNCT)
        if candidate and classify_literal(candidate) == "path":
            out.add(candidate)
    return out


def user_paths(texts: list[str] | tuple[str, ...]) -> set[str]:
    """Every path the user typed — the one human-trusted source of a local path."""
    out: set[str] = set()
    for text in texts or ():
        out |= path_literals(text)
    return out


def synthetic_requested(texts: list[str] | tuple[str, ...], params: dict | None = None) -> bool:
    """True when the USER asked for made-up data, or the model declared
    ``synthetic: true`` — the declaration is only honoured when the user's
    texts justify it (the model may not self-authorize)."""
    lowered = " ".join(t.lower() for t in (texts or ()) if isinstance(t, str))
    asked = any(marker in lowered for marker in SYNTHETIC_MARKERS)
    # ``params`` is accepted so every caller passes the same shape; a bare
    # declaration without the user's words is deliberately NOT enough.
    _ = isinstance(params, dict) and params.get("synthetic") is True
    return asked


def is_data_loading_type(canonical_id: object) -> bool:
    return isinstance(canonical_id, str) and canonical_id.endswith("/data-loading")


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------


def _norm_path(value: str) -> str:
    return os.path.normpath(value.strip())


def _norm_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _catalog_match(literal: str, ctx: GroundingContext) -> CatalogRef | None:
    wanted = _norm_path(literal)
    for path, ref in ctx.catalog_paths.items():
        if _norm_path(path) == wanted:
            return ref
    return None


def _user_match(literal: str, ctx: GroundingContext) -> bool:
    wanted = _norm_path(literal)
    return any(_norm_path(p) == wanted for p in ctx.user_paths)


def _verified_match(literal: str, ctx: GroundingContext) -> dict | None:
    wanted = _norm_url(literal)
    for url, evidence in ctx.verified_urls.items():
        if _norm_url(url) == wanted and (evidence or {}).get("status") == "verified":
            return evidence
    return None


def _http_status(evidence: dict | None) -> int | None:
    status = (evidence or {}).get("httpStatus")
    return status if isinstance(status, int) else None


def check_grounding(code: object, engine: str | None, ctx: GroundingContext) -> GroundingVerdict:
    """The gate. Every path ref must be user- or catalog-known; every URL ref
    must be verified (session evidence or a probe now); a data-loading node
    with no refs needs the synthetic request. Deterministic, model-free."""
    refs = scan_sources(code, engine)
    violations: list[str] = []
    source_refs: list[dict] = []
    for ref in refs:
        where = f"{ref.literal!r} (line {ref.line})"
        if ref.kind == "catalog-id":
            catalog = ctx.catalog_ids.get(ref.literal)
            if catalog is None:
                violations.append(
                    f"curio_dataset_path({ref.literal!r}) (line {ref.line}): not a dataset in "
                    "this project's Data Catalog — use the id of a catalog.search row"
                )
            else:
                source_refs.append({
                    "kind": "catalog",
                    "value": f'curio_dataset_path("{ref.literal}")',
                    "datasetId": catalog.dataset_id,
                    "title": catalog.title[:_TITLE_MAX_CHARS],
                    "format": catalog.format,
                })
            continue
        if ref.kind == "path":
            if ref.partial:
                violations.append(
                    f"{where}: the file name is composed at run time from a prefix — "
                    "write the complete path as one literal so it can be grounded"
                )
                continue
            catalog = _catalog_match(ref.literal, ctx)
            if catalog is not None:
                source_refs.append({
                    "kind": "catalog",
                    "value": ref.literal[:_VALUE_MAX_CHARS],
                    "datasetId": catalog.dataset_id,
                    "title": catalog.title[:_TITLE_MAX_CHARS],
                    "format": catalog.format,
                })
            elif _user_match(ref.literal, ctx):
                source_refs.append({"kind": "user-path", "value": ref.literal[:_VALUE_MAX_CHARS]})
            else:
                violations.append(
                    f"{where}: a local file Curio cannot see — the user gave no such path "
                    "and no Data Catalog dataset resolves to it"
                )
            continue
        # URL
        evidence = _verified_match(ref.literal, ctx)
        if evidence is None:
            if ctx.probe is None:
                violations.append(
                    f"{where}: not verified this run and no probe is available — "
                    "only a URL the runtime has verified may be fetched"
                )
                continue
            try:
                evidence = ctx.probe(ref.literal) or {}
            except Exception as exc:  # a broken prober is a refusal, never a claim
                evidence = {"status": "unreachable", "detail": str(exc)[:200]}
        status = evidence.get("status")
        http_status = _http_status(evidence)
        if status == "verified":
            source_refs.append({
                "kind": "external",
                "value": ref.literal[:_VALUE_MAX_CHARS],
                "verification": evidence,
            })
        elif http_status in (401, 403):
            gated = {
                "kind": "external",
                "value": ref.literal[:_VALUE_MAX_CHARS],
                "verification": evidence,
                "requirement": "credential-gated",
            }
            saved = secret_for_host(ctx, ref.literal)
            if saved is not None:
                gated["hint"] = (
                    f"a connection key {saved.name!r} is saved for this host — use "
                    f"{saved.use_line}"
                )
            source_refs.append(gated)
        else:
            detail = evidence.get("detail") or ""
            if http_status == 400:
                why = "answered 400 — the endpoint exists but this request shape is wrong; check the parameters"
            elif http_status is not None:
                why = f"answered {http_status}"
            elif status == "refused":
                why = f"refused by the egress policy ({detail})" if detail else "refused by the egress policy"
            elif status == "unverified":
                why = detail or "could not be checked"
            else:
                why = detail or "unreachable"
            violations.append(f"{where}: {why} — only a URL the runtime verified may be fetched")
    # dev/116: connection keys by name — known names are grounded refs, an
    # unknown name is refused with the saved names listed (DEC-067).
    saved_names = sorted((ctx.secrets or {}).keys())
    for name, line in secret_calls(code):
        saved = (ctx.secrets or {}).get(name)
        if saved is None:
            listed = f"saved: {', '.join(saved_names)}" if saved_names else "none saved"
            violations.append(
                f"curio_secret({name!r}) (line {line}): no connection key named {name!r} "
                f"({listed}) — save one under Settings → Connection keys, then keep "
                "the call as written"
            )
        else:
            source_refs.append({
                "kind": "secret",
                "value": f'curio_secret("{name}")',
                "name": name,
                "host": saved.host,
                "delivery": saved.delivery,
            })
    # A pasted key never executes, never reaches the journal, never lands in a
    # proposal: the literal is refused and the saved-key route is named.
    for name, line in credential_literals(code, engine):
        violations.append(
            f"{name} (line {line}): a credential literal in node code — save it as a "
            "connection key (Settings → Connection keys) and write "
            'curio_secret("<name>") instead; a key value is never written into a node'
        )
    if not refs and ctx.is_data_loading:
        if ctx.synthetic_requested:
            source_refs.append({"kind": "synthetic"})
        else:
            violations.append(
                "no grounded source: this data-loading node opens no file and fetches no "
                "URL — data invented inline is fabricated evidence unless the user asked "
                "for synthetic data"
            )
    verdict = GroundingVerdict(ok=not violations, violations=violations, refs=refs)
    if verdict.ok and source_refs:
        verdict.source = source_payload(source_refs)
    return verdict


def source_payload(refs: list[dict]) -> dict:
    """The bounded proposal ``source`` payload — plain data for the card."""
    kinds = {r.get("kind") for r in refs}
    kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
    labels: list[str] = []
    for ref in refs[:2]:
        labels.append(_ref_label(ref))
    if len(refs) > 2:
        labels.append(f"…and {len(refs) - 2} more")
    return {
        "kind": kind,
        "label": " · ".join(labels)[:_LABEL_MAX_CHARS],
        "refs": refs[:MAX_REFS],
    }


def _ref_label(ref: dict) -> str:
    kind = ref.get("kind")
    if kind == "catalog":
        fmt = f" ({ref['format']})" if ref.get("format") else ""
        return f"Data Catalog · {ref.get('title') or ref.get('datasetId')}{fmt}"
    if kind == "external":
        status = (ref.get("verification") or {}).get("status", "unverified")
        gate = " · credential-gated" if ref.get("requirement") else ""
        return f"External · {ref.get('value')} · {status}{gate}"
    if kind == "user-path":
        return f"User-provided path · {ref.get('value')}"
    if kind == "secret":
        return f"Connection key · {ref.get('name')} · {ref.get('host')}"
    if kind == "synthetic":
        return "Synthetic · generated in the node, no external source"
    return str(kind)


def refusal_text(verdict: GroundingVerdict, ctx: GroundingContext) -> str:
    """The model-correctable refusal (DEC-067): every violating literal, why,
    and only the routes this run can actually take."""
    lines = [
        f"source grounding refused — {len(verdict.violations)} ungrounded source"
        f"{'s' if len(verdict.violations) != 1 else ''}:"
    ]
    for i, violation in enumerate(verdict.violations, 1):
        lines.append(f"({i}) {violation}")
    allowed = ["a path the user typed in this conversation"]
    allowed.extend(ctx.hints)
    lines.append("Allowed sources: " + "; ".join(allowed) + ".")
    lines.append(
        "Never invent a filename, never assume a file exists, never write a URL from "
        "memory — if no source can be grounded, ask the user for a path or URL instead "
        "of proposing."
    )
    return " ".join(lines)
