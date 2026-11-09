"""The functions node code can call on the wire: a node's, for the header above
its code, and a package's, for its details.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize; every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import g, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import function_nodes as packages_function_nodes
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests


@packages_bp.route("/node-functions", methods=["GET"])
@require_auth
@_map_package_errors
def get_node_functions():
    """``{"engine", "curio", "modules"}``: what the code of a node of
    ``?nodeType=`` can call, as the header above its code lists it
    (``function_nodes.functions_on_the_node``). ``?dataflowId=`` names the
    dataflow the node is in: on a dataflow whose owner invited the caller to
    edit it, a node of a package she put in it lists the modules of her copy,
    which the caller's runs of it import (``node_exec.owners_packages_for``)."""
    from utk_curio.backend.app.execution import node_exec

    node_type, dataflow_id = requests.node_functions_query(request.args)
    owners = node_exec.owners_packages_for(g.user, dataflow_id)
    return jsonify(packages_function_nodes.functions_on_the_node(
        user_key(), node_type, dataflow_id, owners=owners,
    )), 200


@packages_bp.route("/<dir_name>/functions", methods=["GET"])
@require_auth
@_map_package_errors
def get_package_functions(dir_name: str):
    """``{"dirName", "modules"}``: the functions each module of the package
    offers, from the caller's copy, else the catalog's, as View details lists
    them (``function_nodes.package_modules_functions``)."""
    return jsonify(packages_function_nodes.package_modules_functions(user_key(), dir_name)), 200
