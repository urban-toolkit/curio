"""The routes of the requests an invited editor makes of a dataflow's owner (``editor_requests.py``).

One set of routes per kind of request, the same for each: a dataset's at
``/api/dataflows/<id>/datasets/requests``, a package's at
``/api/dataflows/<id>/packages/requests``.
"""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth

requests_bp = Blueprint("editor_requests_api", __name__, url_prefix="/api")

#: The path of each kind's requests, by the kind's name (``editor_requests.KINDS``).
_KIND_PATHS = {"datasets": "/dataflows/<dataflow_id>/datasets/requests",
               "packages": "/dataflows/<dataflow_id>/packages/requests"}


def _for_each_kind(suffix: str, methods: list[str]):
    """Register the decorated handler at each kind's requests path plus
    *suffix*, with the kind's name as its ``kind`` argument."""

    def register(fn):
        for kind, path in _KIND_PATHS.items():
            requests_bp.add_url_rule(f"{path}{suffix}", endpoint=f"{fn.__name__}_{kind}", view_func=fn,
                                     methods=methods, defaults={"kind": kind})
        return fn

    return register


def _map_request_errors(fn):
    """Each refusal as JSON, with its own status: a request's, a dataset's or a
    package's; a dataflow that is gone is 404."""
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
    from utk_curio.backend.app.packages.domain.errors import PackageServiceError
    from utk_curio.backend.app.projects.editor_requests import RequestError
    from utk_curio.backend.app.projects.repositories import NotFoundError

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (RequestError, DatasetCatalogError, PackageServiceError) as exc:
            return jsonify({"error": str(exc)}), getattr(exc, "status", 400)
        except NotFoundError:
            return jsonify({"error": "Dataflow not found"}), 404

    return wrapper


@_for_each_kind("", ["GET"])
@require_auth
@_map_request_errors
def list_requests(dataflow_id: str, kind: str):
    """The requests of the kind the owner has not reviewed, for her and her
    editors; 403 for anyone else."""
    from utk_curio.backend.app.projects import editor_requests

    return jsonify({"requests": editor_requests.pending(g.user, dataflow_id, kind)}), 200


@_for_each_kind("", ["POST"])
@require_auth
@_map_request_errors
def ask_the_owner(dataflow_id: str, kind: str):
    """An invited editor asks the owner to add an item to her dataflow: a
    dataset (``{datasetId, nodeId?, add?}``) or a package
    (``{dirName, nodeId?, add?}``). 201 with the request, or 200 when nothing
    needs asking; 403 for anyone but an editor and the owner, 409 for the
    owner herself."""
    from utk_curio.backend.app.projects import editor_requests

    body = request.get_json(silent=True) or {}
    item = body.get(editor_requests.kind_of(kind).ITEM)
    payload = editor_requests.ask(
        g.user, dataflow_id, kind, item, node_id=body.get("nodeId"), add=bool(body.get("add")),
    )
    return jsonify(payload), 201 if payload.get("requested") else 200


@_for_each_kind("/<request_id>/review", ["GET"])
@require_auth
@_map_request_errors
def review_request(dataflow_id: str, request_id: str, kind: str):
    """What the owner's review shows of a request before her Apply: for a
    package, its manifest as it would be installed and its conflicts with the
    packages of her account. The owner's alone."""
    from utk_curio.backend.app.projects import editor_requests

    return jsonify(editor_requests.review(g.user, dataflow_id, kind, request_id)), 200


@_for_each_kind("/<request_id>/apply", ["POST"])
@require_auth
@_map_request_errors
def apply_request(dataflow_id: str, request_id: str, kind: str):
    """The owner's Apply: the item is copied into her account and added to
    the dataflow as her change. An editor's is refused with 403, as for an
    install."""
    from utk_curio.backend.app.projects import editor_requests

    return jsonify(editor_requests.apply(g.user, dataflow_id, kind, request_id)), 200


@_for_each_kind("/<request_id>", ["DELETE"])
@require_auth
@_map_request_errors
def dismiss_request(dataflow_id: str, request_id: str, kind: str):
    """The owner's Dismiss: the request goes and nothing else changes."""
    from utk_curio.backend.app.projects import editor_requests

    return jsonify(editor_requests.dismiss(g.user, dataflow_id, kind, request_id)), 200
