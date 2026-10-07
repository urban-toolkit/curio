"""The Model Catalog: the models Curio ships, and the ones a person downloaded.

Read the way the Data Catalog reads datasets, with fewer verbs. A shipped
model is used where it is, so there is no install. A downloaded model arrives
from the Discovery Catalog, which hands its folder over here as it hands a
dataset to the Data Catalog. A person may delete their own downloads, never a
shipped model. Models are few and each is one manifest, so a listing reads
the manifests; there is no index table.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from utk_curio.backend.app.model_catalog.domain.manifest import (
    ModelManifest,
    ModelManifestError,
    load_manifest,
    manifest_dict,
    parse_manifest,
)
from utk_curio.backend.app.model_catalog.infrastructure import storage


class ModelCatalogError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class ModelFileUnavailable(ModelCatalogError):
    """A shipped model's entry that the pip package leaves out could not be
    downloaded. The message says what failed and how to get the file."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 502)


def _left_out_entry(folder: Path):
    """Whether an entry of the shipped model in *folder* is a file the pip
    package leaves out, which a pip install downloads the first time a node
    runs the model (``datasets/infrastructure/left_out_files.py``)."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    return lambda entry: left_out_files.is_left_out(f"models/{folder.name}/{entry}")


def _user_key(user) -> str | None:
    if user is None:
        return None
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def model_row(manifest: ModelManifest, *, origin: str, folder: Path) -> dict[str, Any]:
    """What a client is told about one model. Never a path on this machine."""
    row: dict[str, Any] = {
        "id": manifest.id,
        "dirName": manifest.dir_name,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "publisher": manifest.publisher,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "hasLicenseText": bool(manifest.license_file and (folder / manifest.license_file).is_file()),
        "runtime": manifest.runtime,
        "task": manifest.task,
        "labels": list(manifest.labels),
        "labelCount": len(manifest.labels),
        "sizeBytes": manifest.size_bytes,
        "tags": list(manifest.tags),
        "origin": origin,
        "createdAt": manifest.created_at,
    }
    if manifest.input is not None:
        row["input"] = {"width": manifest.input.width, "height": manifest.input.height,
                        "dtype": manifest.input.dtype}
    if manifest.discovery_source:
        row["discoverySource"] = dict(manifest.discovery_source)
    # The libraries its runtime needs, by name: installed when it was added.
    row["dependencies"] = sorted(manifest.python_deps)
    return row


def loader_line(model_id: str) -> str:
    """The line node code loads *model_id* with, as ``resolve_exec_models`` finds it."""
    return f'model = curio_load_model("{model_id}")'


def resolve_exec_models(code: str, user=None) -> dict[str, str]:
    """``{modelId: folder}`` for the models *code* runs as ``curio_load_model("<id>")``.

    Shared by ``/processPythonCode`` and the agent runtime's runs through a
    node, as collections are. *user* defaults to the request's. Fail-open:
    the sandbox's ``curio_load_model`` names a model that is not there.
    """
    from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

    ids = model_ids_in_code(code)
    if not ids:
        return {}
    if user is None:
        try:
            from flask import g, has_request_context

            user = getattr(g, "user", None) if has_request_context() else None
        except Exception:  # noqa: BLE001 - no Flask, no user
            user = None
    try:
        return ModelCatalogService(user).resolve_execution_dirs(ids)
    except Exception as exc:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[exec] model resolution failed: {exc}", flush=True)
        return {}


class ModelCatalogService:
    def __init__(self, user) -> None:
        self.user = user
        self.user_key = _user_key(user)

    # ── reading ────────────────────────────────────────────────────────────

    def _entries(self) -> list[tuple[ModelManifest, str, Path]]:
        """Every model this account can use: its downloads, then the shipped ones.

        A folder whose manifest cannot be read is left out, as the Data Catalog
        leaves out a dataset it cannot read; it is named in the server log.
        """
        found: list[tuple[ModelManifest, str, Path]] = []
        folders = []
        if self.user_key:
            folders += [(folder, "downloaded") for folder in storage.list_user_models(self.user_key)]
        folders += [(folder, "shipped") for folder in storage.list_shipped_models()]
        for folder, origin in folders:
            # A shipped model whose entry the pip package leaves out is listed
            # all the same: resolve_dir fetches the entry when a node runs it.
            fetched = _left_out_entry(folder) if origin == "shipped" else None
            try:
                found.append((load_manifest(folder, fetched_on_first_use=fetched), origin, folder))
            except ModelManifestError as exc:
                print(f"[model catalog] {folder.name} skipped: {exc}", flush=True)
        return found

    def list_catalog(self, *, q: str | None = None) -> dict[str, Any]:
        items = [model_row(m, origin=o, folder=f) for m, o, f in self._entries()]
        if q:
            needle = q.strip().lower()
            items = [
                item for item in items
                if needle in " ".join(
                    [item["name"], item["id"], item["description"], item["publisher"], *item["tags"]]
                ).lower()
            ]
        items.sort(key=lambda item: (item["origin"] != "shipped", item["name"].lower()))
        return {"items": items}

    def _find(self, model_id: str) -> tuple[ModelManifest, str, Path]:
        """The model *model_id* names (``<id>`` or ``<id>@<major>``): a download
        before a shipped one, the highest major of each."""
        want_id, _, want_major = str(model_id).partition("@")
        matches = [
            entry for entry in self._entries()
            if entry[0].id == want_id and (not want_major or str(entry[0].major) == want_major)
        ]
        if not matches:
            raise ModelCatalogError(f"no model {model_id!r} in your Model Catalog", 404)
        matches.sort(key=lambda entry: (entry[1] == "downloaded", entry[0].major), reverse=True)
        return matches[0]

    def get_model(self, model_id: str) -> dict[str, Any]:
        manifest, origin, folder = self._find(model_id)
        return model_row(manifest, origin=origin, folder=folder)

    def license_text(self, model_id: str) -> str:
        manifest, _origin, folder = self._find(model_id)
        if not manifest.license_file:
            raise ModelCatalogError(f"{manifest.name} has no license text", 404)
        path = (folder / manifest.license_file).resolve()
        if not path.is_file() or folder.resolve() not in path.parents:
            raise ModelCatalogError(f"{manifest.name} has no license text", 404)
        return path.read_text(encoding="utf-8", errors="replace")

    def resolve_dir(self, model_id: str) -> Path:
        """The folder a node reads *model_id* from. Server side only.

        For a shipped model whose entry the pip package leaves out, the folder
        a pip install places it in, beside a copy of the model's manifest:
        downloaded from GitHub the first time a node runs the model. Raises
        :class:`ModelFileUnavailable` when the download fails."""
        manifest, origin, folder = self._find(model_id)
        entry = folder / manifest.entry
        if origin != "shipped" or entry.exists():
            return folder
        from utk_curio.backend.app.datasets.infrastructure import left_out_files

        repo_path = f"models/{folder.name}/{manifest.entry}"
        if not left_out_files.is_left_out(repo_path):
            return folder
        try:
            fetched = left_out_files.fetch(repo_path, entry)
        except left_out_files.LeftOutFileUnavailable as exc:
            raise ModelFileUnavailable(str(exc)) from exc
        for _part in Path(manifest.entry).parts:
            fetched = fetched.parent
        return fetched

    def resolve_execution_dirs(self, model_ids: list[str]) -> dict[str, str]:
        """``{modelId: folder}`` for the ids a node's code names that this
        account can use; an unknown id is left out, and the node's
        ``curio_load_model`` names it, as is a model whose entry could not be
        downloaded (``left_out_files.failures`` keeps why for the node)."""
        out: dict[str, str] = {}
        for model_id in model_ids:
            try:
                out[model_id] = str(self.resolve_dir(model_id))
            except ModelCatalogError:
                continue
        return out

    def find_by_discovery_resource(self, source_id: str, resource_id: str) -> dict[str, Any] | None:
        """A model this account already downloaded from that source row."""
        for manifest, origin, folder in self._entries():
            source = manifest.discovery_source or {}
            if origin == "downloaded" and source.get("sourceId") == source_id \
                    and source.get("resourceId") == resource_id:
                return model_row(manifest, origin=origin, folder=folder)
        return None

    # ── changing ───────────────────────────────────────────────────────────

    def install_downloaded(
        self, folder: Path, manifest: dict[str, Any], *, replace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a downloaded model: *folder* holds its files as *manifest*'s
        ``entry`` names them, and is consumed.

        *replace* is the row of a model this account already downloaded from
        the same source row: a refresh. The new files take its place under its
        id, so a node naming that id runs them, and no second copy is kept
        (#623)."""
        if not self.user_key:
            raise ModelCatalogError("sign in to add a model", 401)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        created = now
        if replace is not None:
            model_id = str(replace["id"])
            created = str(replace.get("createdAt") or now)
        else:
            model_id = f"imported.x{uuid.uuid4().hex[:12]}"
        raw = {**manifest, "id": model_id, "compatibility": {"major": 1}, "createdAt": created, "updatedAt": now}
        size = sum(p.stat().st_size for p in Path(folder).rglob("*") if p.is_file())
        raw["sizeBytes"] = size
        parsed = parse_manifest(raw)
        target = storage.user_model_dir(self.user_key, parsed.dir_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.part")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.move(str(folder), str(staging))
        (staging / "manifest.json").write_text(json.dumps(manifest_dict(parsed), indent=2) + "\n", encoding="utf-8")
        if target.exists():
            # A refresh: swap the folders, then drop the old one.
            retired = target.with_name(f".{target.name}.old")
            shutil.rmtree(retired, ignore_errors=True)
            os.replace(target, retired)
            os.replace(staging, target)
            shutil.rmtree(retired, ignore_errors=True)
        else:
            os.replace(staging, target)
        loaded = load_manifest(target)
        return model_row(loaded, origin="downloaded", folder=target)

    def model_refusal(self) -> str | None:
        """Why this account may not add a model, or ``None``: the rule a
        package install follows. A local run always may; a guest on a
        ``--deploy`` instance may not, because every guest shares one account
        and its disk (#623)."""
        from utk_curio.backend.app.users.capabilities import install_refusal

        return install_refusal(self.user, noun="models")

    def install_refusal(self) -> str | None:
        """Why this account may not install libraries, as for a package: a
        model whose runtime needs some is refused for the same reason."""
        from utk_curio.backend.app.users.capabilities import package_install_refusal

        return package_install_refusal(self.user)

    def install_dependencies(self, model_id: str) -> dict[str, Any]:
        """Install the libraries *model_id*'s runtime needs, by the path a
        package's ``dependencies.python`` takes (``provision_declared_deps``):
        the shared interpreter, or this account's own node libraries under
        isolation. A pip failure is reported, not raised, and the model stays."""
        manifest, _origin, _folder = self._find(model_id)
        if not manifest.python_deps:
            return {"importErrors": {}}
        from types import SimpleNamespace

        from utk_curio.backend.app.packages.application.provisioning import provision_declared_deps

        # The routing rule reads a package's backend surface and templates; a
        # model has neither, so its libraries go where node code finds them.
        declaration = SimpleNamespace(python_deps=dict(manifest.python_deps), backend=None, templates=())
        return provision_declared_deps(self.user_key or "-", manifest.dir_name, declaration)

    def delete_model(self, model_id: str) -> dict[str, Any]:
        manifest, origin, folder = self._find(model_id)
        if origin != "downloaded":
            raise ModelCatalogError(f"{manifest.name} ships with Curio and cannot be deleted", 403)
        shutil.rmtree(folder)
        return {"deleted": manifest.id}
