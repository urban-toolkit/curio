"""The Model Catalog: the model packages one account can add or run.

A model is a node package of kind ``model``, with its weights. The catalog
lists the ones Curio ships, and those imported, published or downloaded from
the Discovery Catalog into a person's store
(``packages.service.list_model_packages``). Their details and license read
their ``model`` block, and a person's own is deleted as the Node Catalog
removes a package. A node reaches their weights through
``packages.service.resolve_model_dirs``, from the person's store only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.model_catalog.domain.manifest import ModelInput, ModelManifest


class ModelCatalogError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _manifest_of_package(package) -> ModelManifest:
    """A model package's manifest (``packages.service.PackageManifest``) as
    this catalog's: the package's id, name, version and description, its
    ``model`` block's fields, and the weights' publisher and license."""
    block = package.model
    spec = block.input
    model_input = None if spec is None else ModelInput(
        width=spec.width, height=spec.height, dtype=spec.dtype, layout=spec.layout,
        scale=spec.scale, mean=spec.mean, std=spec.std,
    )
    return ModelManifest(
        id=package.package_id, major=package.major, name=package.name, version=package.version,
        runtime=block.runtime, task=block.type, entry=block.entry, license=block.license,
        description=package.description, publisher=block.publisher or package.publisher,
        homepage=block.homepage, license_file=block.license_file, labels=block.labels,
        input=model_input, size_bytes=block.size_bytes, discovery_source=block.discovery_source,
        python_deps=dict(package.python_deps), created_at=package.created_at_iso,
    )


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


class ModelCatalogService:
    def __init__(self, user) -> None:
        self.user = user
        self.user_key = _user_key(user)

    # ── reading ────────────────────────────────────────────────────────────

    def _entries(self) -> list[tuple[ModelManifest, str, Path]]:
        """The model packages this account can add or run, as this catalog's
        entries: one in the account's store with its own weights is
        ``downloaded``, one that ships with Curio ``shipped`` (a store copy of
        it holds no weights, so it is the shipped one)."""
        from utk_curio.backend.app.packages.service import list_model_packages

        return [
            (_manifest_of_package(listed.manifest), "downloaded" if listed.in_store else "shipped", listed.folder)
            for listed in list_model_packages(self.user_key)
        ]

    def _is_store_package(self, folder: Path) -> bool:
        """Whether *folder* is a package in this account's store."""
        if not self.user_key:
            return False
        from utk_curio.backend.app.packages.service import user_packages_dir

        return Path(folder).resolve().parent == user_packages_dir(self.user_key).resolve()

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
        """The model *model_id* names (``<id>`` or ``<id>@<major>``): a person's
        own before a shipped one, the highest major of each."""
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

    def find_by_discovery_resource(self, source_id: str, resource_id: str) -> dict[str, Any] | None:
        """A model this account already downloaded from that source row."""
        for manifest, origin, folder in self._entries():
            source = manifest.discovery_source or {}
            if origin == "downloaded" and source.get("sourceId") == source_id \
                    and source.get("resourceId") == resource_id:
                return model_row(manifest, origin=origin, folder=folder)
        return None

    # ── changing ───────────────────────────────────────────────────────────

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

    def delete_model(self, model_id: str) -> dict[str, Any]:
        """Remove a model package of this account's own, as the Node Catalog
        removes a package: from the store, and from every dataflow's lockfile
        that names it. One that ships with Curio is refused."""
        manifest, origin, folder = self._find(model_id)
        if origin != "downloaded" or not self._is_store_package(folder):
            raise ModelCatalogError(f"{manifest.name} ships with Curio and cannot be deleted", 403)
        from utk_curio.backend.app.packages.service import detach_from_all_projects, remove_package

        remove_package(self.user_key, manifest.dir_name)
        detach_from_all_projects(self.user_key, manifest.dir_name)
        return {"deleted": manifest.id}
