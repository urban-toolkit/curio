"""The per-user package store on the wire: the installed list, sideload, uninstall, the metadata PATCH, the archive re-export and the package-file server.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import Response, current_app, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.application import (
    catalog as packages_catalog,
    metadata as packages_metadata,
    package_files as packages_package_files,
    project_packages as packages_project_packages,
    provisioning as packages_provisioning,
    seeding as packages_seeding,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests
from utk_curio.backend.app.packages.schemas.responses import package_payload


@packages_bp.route("", methods=["GET"])
@require_auth
@_map_package_errors
def list_installed_packages():
    """Every package in the caller's store, newest ``createdAt`` first."""
    key = user_key()
    packages_seeding.ensure_user_seeded(key)
    return jsonify({"packages": packages_catalog.installed_package_payloads(key)}), 200


@packages_bp.route("/upload", methods=["POST"])
@require_auth
@_map_package_errors
def upload_package():
    """Sideload a ``.curio.zip`` for the current user (multipart field ``file``;
    ``?replace=true`` overwrites an installed coordinate). The archive is read
    into memory once (the installer caps it at 128 MiB uncompressed). Installs
    the manifest's declared python deps too, and says whether they import — a
    sideloaded package's libraries used to be nobody's job."""
    packages_provisioning.assert_may_install()
    key = user_key()
    upload = requests.uploaded_archive(request.files)
    replace = request.args.get("replace", "false").lower() == "true"
    try:
        result = packages_store_install.install_package_from_archive(
            key, upload.stream.read(), replace=replace,
        )
    except (InstallerError, PackageIdError) as exc:
        # Logged, not only returned. The reason reaches the browser and stops
        # there: a rejected sideload in CI left a 400 in the access log with
        # nothing to say which archive or why, and the e2e failure that
        # followed was a timeout on the NEXT request, two steps from the
        # cause. ``_map_package_errors`` still answers the 400.
        current_app.logger.warning(
            "package upload rejected: filename=%s replace=%s reason=%s",
            upload.filename, replace, exc,
        )
        raise
    return jsonify(_installed_payload(key, result)), 201


def _installed_payload(key: str, result) -> dict:
    """The body every store install answers: the package, its integrity, whether
    it replaced a copy, and the dependency step's additive fields."""
    return {
        "package": package_payload(result.manifest, package_mtime_path=package_dir(key, result.manifest.dir_name)),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        **packages_provisioning.provision_declared_deps(key, result.manifest.dir_name, result.manifest),
    }


@packages_bp.route("/<dir_name>", methods=["DELETE"])
@require_auth
@_map_package_errors
def remove_package(dir_name: str):
    """Uninstall from the store with the backend residue (dev/97); the builtin is refused."""
    key = user_key()
    packages_store_install.remove_package(key, dir_name)
    # ...and so do the lockfile entries that named it. Without this every
    # dataflow that had the package kept a reference to something no longer
    # installed, and reopening it retried an install that cannot succeed.
    # Composed here rather than inside ``remove_package``: the lockfile use
    # cases already import the store ones, and the layers do not import upward.
    packages_project_packages.detach_from_all_projects(key, dir_name)
    return "", 204


@packages_bp.route("/<dir_name>", methods=["PATCH"])
@require_auth
@_map_package_errors
def patch_package_metadata(dir_name: str):
    """Partial-update human-authored package metadata (see ``application.metadata``)."""
    manifest, pkg_path = packages_metadata.patch_package_metadata(
        user_key(), dir_name, request.get_json(silent=True),
    )
    return jsonify({"package": package_payload(manifest, package_mtime_path=pkg_path)}), 200


@packages_bp.route("/<dir_name>/archive", methods=["GET"])
@require_auth
@_map_package_errors
def download_package_archive(dir_name: str):
    """Re-export as a deterministic ``.curio.zip`` — the store copy, else the catalog copy (#275)."""
    body = packages_store_install.archive_for_download(user_key(), dir_name)
    response = Response(body, mimetype="application/zip")
    response.headers["Content-Disposition"] = f'attachment; filename="{dir_name}.curio.zip"'
    return response


@packages_bp.route("/<dir_name>/file/<path:filename>", methods=["GET"])
@require_auth
@_map_package_errors
def get_package_file(dir_name: str, filename: str):
    """Serve a static file from the user's installed copy of ``<dir_name>`` —
    the dynamic behavior loader's ``behaviors.js``, or any package-shipped asset."""
    body, mimetype = packages_package_files.package_file(user_key(), dir_name, filename)
    response = Response(body, mimetype=mimetype)
    # Package files are content-addressed via integrity.json - once a sha
    # matches, the file is immutable for this install. A short browser
    # cache is safe and keeps the dynamic loader fast on repeat boots.
    response.headers["Cache-Control"] = "private, max-age=300"
    return response
