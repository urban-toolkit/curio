"""Hugging Face models: the Hub searched for models Curio can run.

A model source, the catalog's fourth family. It is searched like a portal,
and an add lands in the Model Catalog rather than the Data Catalog.

- **Search** asks ``/api/models`` for the manifest's ``pipelineTag`` (image
  segmentation) and keeps the repos whose tags say they hold ONNX or
  safetensors weights, the two Curio loads. A Hub search never says more than
  that; what a repo holds is read when it is described or added.
- **Describe and add** read ``/api/models/<repo>?blobs=true``, the file list
  with sizes, pinned to the commit it names, and choose the files to fetch:
  - ONNX: the ``.onnx`` graph (``model.onnx`` first, then the quantized one)
    with the external data it names, and the ``config.json`` and
    ``preprocessor_config.json`` that give its labels and its input;
  - Transformers: ``config.json``, ``preprocessor_config.json`` and
    safetensors weights, for a ``...ForSemanticSegmentation`` architecture.
    A repo whose only weights are ``pytorch_model.bin`` is refused: loading
    one runs Python pickles, and Curio does not run a stranger's code to read
    weights.
- Files come from ``/<repo>/resolve/<commit>/<path>``, which redirects to the
  Hub's CDN. The transport sends a person's Hugging Face token to
  ``huggingface.co`` only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    DownloadTooLarge,
    ProviderError,
    ResourceNotFound,
)
from utk_curio.backend.app.discovery.domain.resource import (
    DiscoveryResource,
    DiscoveryResourceDetail,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.discovery.providers.base import BaseProvider

#: The most one model may be, all its files together.
MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024

#: Tags that say a repo holds weights Curio loads.
LOADABLE_TAGS = ("onnx", "safetensors")

_ONNX_PREFERENCE = ("onnx/model.onnx", "model.onnx", "onnx/model_quantized.onnx", "model_quantized.onnx")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ModelPlan:
    """What adding a repo fetches, and what it will be."""

    repo: str
    revision: str
    runtime: str
    #: Repo paths and their sizes.
    files: tuple[tuple[str, int], ...]
    #: The ``.onnx`` graph's repo path, or "" for a Transformers checkpoint.
    graph: str
    license: str
    architecture: str | None = None

    #: Whether the Hub asks people to accept terms before they download it.
    gated: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(size for _path, size in self.files)


def _license(info: dict[str, Any]) -> str:
    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    value = card.get("license")
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    if not value:
        tags = [t for t in info.get("tags") or [] if isinstance(t, str) and t.startswith("license:")]
        value = tags[0].split(":", 1)[1] if tags else ""
    return str(value or "")


class HuggingFaceModels(BaseProvider):
    type = "huggingface-models"
    resource_id_re = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}$")

    # ── search ─────────────────────────────────────────────────────────────

    def search(self, query: SearchQuery) -> SearchPage:
        params: dict[str, Any] = {
            "pipeline_tag": self.option("pipelineTag", "image-segmentation"),
            "sort": "downloads",
            "direction": "-1",
            "limit": max(1, min(int(query.limit or 20), 50)),
        }
        if query.text.strip():
            params["search"] = query.text.strip()[:100]
        if query.cursor:
            params["cursor"] = query.cursor
        body, headers = self.transport.get_page(f"{self.base}/api/models?" + urlencode(params))
        try:
            hits = json.loads(body)
        except ValueError as exc:
            raise ProviderError("Hugging Face answered a search that is not JSON") from exc
        if not isinstance(hits, list):
            raise ProviderError("Hugging Face answered a search in an unknown shape")
        rows = tuple(row for row in (self._row(hit) for hit in hits) if row is not None)
        return SearchPage(resources=rows, next_cursor=_next_cursor(headers))

    def _row(self, hit: object) -> DiscoveryResource | None:
        if not isinstance(hit, dict):
            return None
        repo = str(hit.get("id") or hit.get("modelId") or "")
        if not self.resource_id_re.match(repo) or hit.get("private"):
            return None
        tags = [t for t in hit.get("tags") or [] if isinstance(t, str)]
        if not any(tag in tags for tag in LOADABLE_TAGS):
            return None
        weights = " and ".join(t.upper() if t == "onnx" else t for t in LOADABLE_TAGS if t in tags)
        downloads = hit.get("downloads")
        description = f"{hit.get('pipeline_tag') or 'model'}, {weights} weights"
        if isinstance(downloads, int):
            description += f", {downloads:,} downloads"
        license_tag = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
        if license_tag:
            description += f", license {license_tag}"
        return DiscoveryResource(
            source_id=self.manifest.id,
            resource_id=repo,
            name=repo,
            description=description,
            publisher=repo.split("/", 1)[0],
            formats=("model",),
            kind="model",
            landing_url=f"{self.base}/{repo}",
            updated_at=hit.get("lastModified") or hit.get("createdAt"),
        )

    # ── describe ───────────────────────────────────────────────────────────

    def info(self, repo: str) -> dict[str, Any]:
        self.validate_resource_id(repo)
        body = self.transport.json_get(f"{self.base}/api/models/{repo}?blobs=true")
        try:
            info = json.loads(body)
        except ValueError as exc:
            raise ProviderError("Hugging Face answered a model that is not JSON") from exc
        if not isinstance(info, dict) or info.get("id") != repo and info.get("modelId") != repo:
            raise ResourceNotFound(f"Hugging Face has no model {repo!r}")
        return info

    def plan(self, repo: str, info: dict[str, Any] | None = None) -> ModelPlan:
        """The files to fetch for *repo*, or a refusal that says why not."""
        info = info if info is not None else self.info(repo)
        revision = str(info.get("sha") or "")
        if not _SHA_RE.match(revision):
            raise ProviderError(f"Hugging Face named no commit for {repo}")
        sizes = {
            str(s.get("rfilename")): int(s.get("size") or 0)
            for s in info.get("siblings") or []
            if isinstance(s, dict) and s.get("rfilename")
        }
        for needed in ("config.json", "preprocessor_config.json"):
            if needed not in sizes:
                raise CapabilityUnsupported(f"{repo} has no {needed}, which says how to read its output")
        graph = next((path for path in _ONNX_PREFERENCE if path in sizes), None) or next(
            (path for path in sorted(sizes) if path.endswith(".onnx")), None
        )
        architecture = None
        config = info.get("config") if isinstance(info.get("config"), dict) else {}
        architectures = [str(a) for a in config.get("architectures") or []]
        if graph:
            data = [p for p in sizes if p in (f"{graph}_data", f"{graph}.data")]
            paths = ["config.json", "preprocessor_config.json", graph, *data]
            runtime = "onnx"
        else:
            architecture = next((a for a in architectures if a.endswith("ForSemanticSegmentation")), None)
            if architecture is None:
                raise CapabilityUnsupported(
                    f"{repo} is not a semantic segmentation model Curio runs "
                    f"(its architecture is {', '.join(architectures) or 'not named'})"
                )
            shards = sorted(p for p in sizes if "/" not in p and p.endswith(".safetensors"))
            if not shards:
                bins = [p for p in sizes if p.endswith(".bin")]
                raise CapabilityUnsupported(
                    f"{repo} has only {', '.join(bins) or 'no'} weights; Curio runs safetensors "
                    "or ONNX weights, which load without running code"
                )
            index = ["model.safetensors.index.json"] if "model.safetensors.index.json" in sizes else []
            paths = ["config.json", "preprocessor_config.json", *index, *shards]
            runtime = "transformers"
        plan = ModelPlan(
            repo=repo, revision=revision, runtime=runtime,
            files=tuple((path, sizes[path]) for path in paths),
            graph=graph or "", license=_license(info), architecture=architecture,
            gated=info.get("gated") not in (None, False, "false"),
        )
        if plan.total_bytes > MAX_MODEL_BYTES:
            raise DownloadTooLarge(
                f"{repo} is {plan.total_bytes / 1024 ** 3:.1f} GB; a model may be at most "
                f"{MAX_MODEL_BYTES // 1024 ** 3} GB"
            )
        return plan

    def describe(self, resource_id: str) -> DiscoveryResourceDetail:
        info = self.info(resource_id)
        row = self._row({**info, "tags": info.get("tags") or []}) or DiscoveryResource(
            source_id=self.manifest.id, resource_id=resource_id, name=resource_id,
            formats=("model",), kind="model", landing_url=f"{self.base}/{resource_id}",
        )
        extra: dict[str, Any] = {"pipelineTag": info.get("pipeline_tag"), "library": info.get("library_name")}
        try:
            plan = self.plan(resource_id, info)
            extra.update({"runtime": plan.runtime, "files": [p for p, _s in plan.files], "totalBytes": plan.total_bytes})
        except (CapabilityUnsupported, DownloadTooLarge) as exc:
            extra["cannotAdd"] = str(exc)
        return DiscoveryResourceDetail(resource=row, license=_license(info), extra=extra)

    def file_url(self, plan: ModelPlan, path: str) -> str:
        return self.assert_on_base(f"{self.base}/{plan.repo}/resolve/{plan.revision}/{quote(path)}")

    def download_url(self, resource_id, fmt, *, values=None):  # pragma: no cover - models add whole
        raise self.unsupported("a single-file download")


def _next_cursor(headers: dict[str, Any]) -> str | None:
    """The ``cursor`` of a ``Link: <...>; rel="next"`` header, if any."""
    link = next((v for k, v in (headers or {}).items() if k.lower() == "link"), None)
    if not link:
        return None
    for part in str(link).split(","):
        if 'rel="next"' in part and "<" in part and ">" in part:
            target = part[part.index("<") + 1:part.index(">")]
            values = parse_qs(urlsplit(target).query).get("cursor")
            if values:
                return values[0]
    return None


__all__ = ["HuggingFaceModels", "ModelPlan", "MAX_MODEL_BYTES"]
