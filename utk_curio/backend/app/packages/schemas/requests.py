"""Request-body parsers for the packages API (memo dev/143, B4): each takes the
parsed JSON (or the form files) and returns the typed value, or raises a
:class:`PackageServiceError` carrying the exact complaint and status the route
answered with before. Handlers parse, call and serialize; the texts live here.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain import backend_contract as bc
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE

PACKAGES_BODY_SHAPE = "body must be {'packages': [<dirName>, ...]}"


def catalog_dir_name(body: Mapping[str, Any]) -> str:
    """``dirName`` for a catalog install: present and well-formed."""
    dir_name = body.get("dirName")
    if not isinstance(dir_name, str) or not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError("body must include a valid 'dirName' (<packageId>@<major>)")
    return dir_name


def dir_name(body: Mapping[str, Any]) -> str:
    """``dirName`` for a project or defaults install: present (the use case validates its shape)."""
    value = body.get("dirName")
    if not isinstance(value, str):
        raise PackageServiceError("body must include 'dirName'")
    return value


_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def function_template(body: Mapping[str, Any]) -> tuple[str, str, str, str | None, dict]:
    """``dirName``, ``module``, ``function``, ``label`` and ``bindings`` for New
    node from a Python function."""
    package = body.get("dirName")
    if not isinstance(package, str) or not PACKAGE_DIR_RE.match(package):
        raise PackageServiceError("body must include a valid 'dirName' (<packageId>@<major>)")
    module = body.get("module")
    if not isinstance(module, str) or not _DOTTED_RE.match(module):
        raise PackageServiceError("body must include 'module', a dotted module name")
    function = body.get("function")
    if not isinstance(function, str) or not function.isidentifier():
        raise PackageServiceError("body must include 'function', a function name")
    label = body.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 120):
        raise PackageServiceError("'label' must be a text of at most 120 characters")
    bindings = body.get("bindings")
    if not isinstance(bindings, dict):
        raise PackageServiceError("body must include 'bindings', an object of {parameter: {use}}")
    return package, module, function, label, bindings


def replace_flag(body: Mapping[str, Any]) -> bool:
    return bool(body.get("replace", False))


def package_names(body: Mapping[str, Any]) -> list[str]:
    """``packages`` for the resolve probe: a list of strings."""
    packages = body.get("packages")
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        raise PackageServiceError(PACKAGES_BODY_SHAPE)
    return packages


def declared_packages(body: Mapping[str, Any]) -> list:
    """``packages`` for the workflow-deps check: a list (items are filtered by the use case)."""
    packages = body.get("packages") or []
    if not isinstance(packages, list):
        raise PackageServiceError(PACKAGES_BODY_SHAPE)
    return packages


def packages_to_install(body: Mapping[str, Any]) -> list[str]:
    """``packages`` for the workflow-deps install: a non-empty list of well-formed dirNames."""
    pkg_dirs = body.get("packages") or []
    if not isinstance(pkg_dirs, list) or not pkg_dirs:
        raise PackageServiceError(PACKAGES_BODY_SHAPE)
    for name in pkg_dirs:
        if not isinstance(name, str) or not PACKAGE_DIR_RE.match(name):
            raise PackageServiceError(f"invalid package dirName: {name!r}")
    return pkg_dirs


def library_spec(body: Mapping[str, Any]) -> tuple[str, str]:
    """``(kind, spec)`` for a standalone library: a non-empty spec, a known kind."""
    kind = body.get("kind")
    spec = body.get("spec")
    if not isinstance(spec, str) or not spec.strip():
        raise PackageServiceError("body must include non-empty 'spec'")
    if kind not in ("python", "js"):
        raise PackageServiceError("kind must be 'python' or 'js'")
    return kind, spec


def library_kind(kind: str) -> str:
    if kind not in ("python", "js"):
        raise PackageServiceError("kind must be 'python' or 'js'")
    return kind


def invoke_payload(content_length: int | None, body: Any) -> Any:
    """The ``payload`` of a backend invocation, bounded before any worker is spent (413 / 422)."""
    if content_length and content_length > bc.PAYLOAD_MAX_BYTES + 4096:
        raise PackageServiceError(
            f"payload exceeds the {bc.PAYLOAD_MAX_BYTES // (1024 * 1024)} MiB "
            "request bound", 413,
        )
    if not isinstance(body, dict) or "payload" not in body:
        raise PackageServiceError('body must be a JSON object with a "payload" member', 422)
    return body["payload"]


def uploaded_archive(files: Mapping[str, Any]):
    """The multipart ``file`` field of a sideload."""
    if "file" not in files:
        raise PackageServiceError("missing 'file' form field with a .curio.zip archive")
    upload = files["file"]
    if not upload.filename:
        raise PackageServiceError("uploaded file is empty (no filename)")
    return upload
