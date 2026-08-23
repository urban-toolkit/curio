"""Drift guards for the portable ``curio_dataset_path`` contract.

Three independent copies of the same dataset-id grammar decide whether a
generated loader snippet is safe, and two independent copies of the same cap
bound how many ids one execution may resolve. They sit in three languages and
two processes, so nothing but a test keeps them equal:

* the frontend generator decides whether to emit an id call at all;
* the backend generator makes the same decision server-side;
* the backend scanner decides which emitted calls it will resolve;
* the backend and the sandbox each independently truncate the id list.

A one-sided edit degrades quietly. Loosen the scanner alone and ids the
generators refuse to emit become resolvable; tighten it alone and legitimately
generated snippets stop resolving and fail at runtime instead. Raise one cap
alone and the extra ids are silently dropped by whichever side kept the lower
number. This module follows the precedent in ``test_sink_node_type_parity.py``
and regexes the TS source so either side failing to move fails CI.
"""
from __future__ import annotations

import re
from pathlib import Path

from utk_curio.backend.app.api.routes import (
    MAX_EXEC_DATASET_IDS,
    _DATASET_PATH_CALL_RE,
)
from utk_curio.backend.app.datasets.domain.catalog_item import _SAFE_DATASET_ID_RE

REPO_ROOT = Path(__file__).resolve().parents[4]
SNIPPETS_TS = (
    REPO_ROOT
    / "utk_curio/frontend/urban-workflows/src/services/datasetCatalog/datasetLoaderSnippets.ts"
)
SANDBOX_API = REPO_ROOT / "utk_curio/sandbox/app/api.py"

# The shared grammar, written once here. Every copy below must reduce to it.
ID_BODY = "[A-Za-z0-9][A-Za-z0-9._@-]{0,199}"


def _frontend_id_regex() -> str:
    src = SNIPPETS_TS.read_text(encoding="utf-8")
    match = re.search(r"SAFE_DATASET_ID_RE\s*=\s*/\^(.+?)\$/", src)
    assert match, f"could not find SAFE_DATASET_ID_RE in {SNIPPETS_TS}"
    return match.group(1)


def test_backend_generator_and_frontend_generator_share_the_id_grammar():
    backend = _SAFE_DATASET_ID_RE.pattern
    assert backend == f"^{ID_BODY}$", backend
    assert _frontend_id_regex() == ID_BODY, _frontend_id_regex()


def test_the_scanner_accepts_exactly_what_the_generators_emit():
    scanner_body = re.search(
        r"\(\[A-Za-z0-9\]\[A-Za-z0-9\._@-\]\{0,199\}\)", _DATASET_PATH_CALL_RE.pattern
    )
    assert scanner_body, _DATASET_PATH_CALL_RE.pattern

    # Behavioural check, not just textual: agreement on concrete ids.
    accepted = [
        "imported.cities",
        "computed.flow-1.node_2@1",
        "a",
        "A0._@-" + "x" * 100,
        "x" * 200,
    ]
    rejected = ["", ".leading", "-leading", "_leading", "has space", "quote\"id", "x" * 201]

    for dataset_id in accepted:
        assert _SAFE_DATASET_ID_RE.match(dataset_id), dataset_id
        assert _DATASET_PATH_CALL_RE.search(
            f'curio_dataset_path("{dataset_id}")'
        ), dataset_id

    for dataset_id in rejected:
        assert not _SAFE_DATASET_ID_RE.match(dataset_id), dataset_id
        assert not _DATASET_PATH_CALL_RE.search(
            f'curio_dataset_path("{dataset_id}")'
        ), dataset_id


def test_scanner_accepts_both_quote_styles():
    for quoted in ('"imported.x"', "'imported.x'"):
        assert _DATASET_PATH_CALL_RE.search(f"curio_dataset_path({quoted})")
    # Mismatched quotes are not a call.
    assert not _DATASET_PATH_CALL_RE.search("curio_dataset_path(\"imported.x')")


def test_sandbox_cap_matches_the_backend_cap():
    """The sandbox truncates ``dataset_paths`` independently of the backend.

    ``sandbox/app/api.py`` cannot import the backend, so it carries a bare
    literal. If the backend cap is raised without touching it, every id past the
    sandbox's limit is dropped and the node fails with a confusing per-id error.
    """
    src = SANDBOX_API.read_text(encoding="utf-8")
    match = re.search(r"list\(dataset_paths\.items\(\)\)\[:(\d+)\]", src)
    assert match, f"could not find the dataset_paths truncation in {SANDBOX_API}"
    assert int(match.group(1)) == MAX_EXEC_DATASET_IDS, (
        f"sandbox truncates at {match.group(1)} but the backend cap is "
        f"{MAX_EXEC_DATASET_IDS}"
    )
