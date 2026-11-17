"""What a shipped dataflow's e2e runs on where CI lacks the real thing.

Example 31 (``31-sideseeing-objects-along-a-walk.json``) reads two things no
CI run holds, and the generic matrix runs it as it ships, on stand-ins put
in place around its class by ``loaded_workflow`` (``fixtures.py``), from what
the dataflow declares:

- the weights a model package's ``fetch`` names, which a node's first run
  downloads (SAM 3's, Meta's 3.4 GB): a tiny model of the package
  (``STAND_INS``), planted as fetched in the backend's catalog through
  ``/api/testing/fetched-weights`` (:func:`fetched_weights_planted`) and
  taken out after, once the Model Catalog says the weights download on first
  use again, so no later test sees the plant;
- a committed collection whose files are in a bucket, which no CI stack
  mounts: its files cached for the account first, as the Data Catalog's
  **Cache files** caches them, from the recorded corpus the stack reads
  buckets from (:func:`cache_bucket_collections`).
"""

from __future__ import annotations

import base64
import contextlib
import json
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.error import HTTPError

from utk_curio.backend.tests._support import tiny_sam3

from .db_stubs import api_json
from .environment import REPO_ROOT

REPO_ROOT_PATH = Path(REPO_ROOT)

#: The model packages whose weights no CI run holds, each with the builder of
#: the files of a tiny model of it, by their path in the package's entry.
STAND_INS = {"model.curio.sam3@1": tiny_sam3.checkpoint_files}
#: How long a plant of a stand-in's files, a few tens of megabytes in base64,
#: may take to answer.
PLANT_TIMEOUT_S = 180.0
#: How long the account's copy of a bucket collection's files may take.
CACHE_TIMEOUT_S = 300.0
_JOB_ENDS = ("completed", "failed", "refused", "cancelled")


def _testing_post(backend_url: str, route: str, payload: dict, *, timeout: float) -> dict:
    """POST *payload* to ``/api/testing/<route>``, which takes no sign-in,
    failing with the route's own answer."""
    try:
        # api_json sends a token whatever the route; the testing routes read none.
        return api_json(f"{backend_url}/api/testing/{route}", "unused", method="POST", payload=payload,
                        timeout=timeout)
    except HTTPError as error:
        raise AssertionError(f"/api/testing/{route} answered {error.code}: {error.read().decode('utf-8', 'replace')}") from error


def declared_stand_ins(spec: dict) -> list[str]:
    """The packages *spec*'s dataflow declares that a stand-in is planted for."""
    return [dir_name for dir_name in (spec.get("dataflow") or {}).get("packages") or [] if dir_name in STAND_INS]


def _downloads_on_first_use(backend_url: str, token: str, dir_name: str) -> bool:
    """Whether the Model Catalog says *dir_name*'s weights download on a
    node's first run: what its card's Weights row reads."""
    rows = api_json(f"{backend_url}/api/packages/catalog?kind=model", token)["packages"]
    (row,) = [row for row in rows if row.get("dirName") == dir_name]
    return bool(row["model"].get("downloadsOnFirstUse"))


@contextlib.contextmanager
def fetched_weights_planted(backend_url: str, token: str, dir_names: Iterable[str]) -> Iterator[None]:
    """Each package of *dir_names* with its stand-in planted as fetched, and
    taken out afterwards whatever happened. Before the plant and after the
    removal the Model Catalog must say its weights download on first use, so
    the stand-in reached no test before or after."""
    planted = []
    try:
        for dir_name in dir_names:
            assert _downloads_on_first_use(backend_url, token, dir_name), (
                f"the Model Catalog says {dir_name}'s weights are here before the stand-in is planted")
            files = {rel: base64.b64encode(data).decode("ascii") for rel, data in STAND_INS[dir_name]().items()}
            planted.append(dir_name)
            answer = _testing_post(backend_url, "fetched-weights",
                                   {"action": "plant", "dirName": dir_name, "files": files}, timeout=PLANT_TIMEOUT_S)
            assert answer.get("planted") == dir_name, answer
            assert not _downloads_on_first_use(backend_url, token, dir_name), (
                f"the Model Catalog says {dir_name}'s weights download on first use with its stand-in planted")
        yield
    finally:
        left = []
        for dir_name in planted:
            _testing_post(backend_url, "fetched-weights", {"action": "remove", "dirName": dir_name},
                          timeout=PLANT_TIMEOUT_S)
            if not _downloads_on_first_use(backend_url, token, dir_name):
                left.append(dir_name)
        assert not left, f"the Model Catalog still says the weights of {left} are here once their stand-ins are out"


def declared_bucket_collections(spec: dict) -> list[str]:
    """The datasets *spec*'s dataflow declares that are committed collections
    whose files are in a bucket (``dataset_catalog_coverage.bucket_source``),
    read from their manifests in ``datasets/``."""
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
    from utk_curio.backend.tests.dataset_catalog_coverage import CatalogDataset, bucket_source

    found = []
    for ref in (spec.get("dataflow") or {}).get("datasets") or []:
        root = REPO_ROOT_PATH / "datasets" / str(ref.get("dirName") or "")
        if not (root / "manifest.json").is_file():
            continue
        if bucket_source(CatalogDataset(root=root, manifest=load_dataset_manifest(root))) is not None:
            found.append(ref["datasetId"])
    return sorted(found)


def cache_bucket_collections(backend_url: str, token: str, dataset_ids: Iterable[str]) -> None:
    """Cache, for the account signed in as *token*, every file of each
    collection of *dataset_ids*, as the Data Catalog's **Cache files** does,
    and wait until the collection says each is on this machine."""
    for dataset_id in dataset_ids:
        started = api_json(f"{backend_url}/api/discovery/collections/{dataset_id}/cache", token,
                           method="POST", payload={})
        deadline = time.monotonic() + CACHE_TIMEOUT_S
        job = {"status": "queued"}
        while job.get("status") not in _JOB_ENDS and time.monotonic() < deadline:
            time.sleep(0.5)
            job = api_json(f"{backend_url}/api/discovery/jobs/{started['jobId']}", token)
        assert job.get("status") == "completed", f"Cache files of {dataset_id} ended {json.dumps(job)[:600]}"
        status = api_json(f"{backend_url}/api/discovery/collections/{dataset_id}", token)
        assert status["cachedFiles"] == status["fileCount"] > 0, (
            f"Cache files of {dataset_id} left {status['cachedFiles']} of its {status['fileCount']} files on this machine")
