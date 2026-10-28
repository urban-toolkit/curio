"""The dataflow block a run that writes code is given, gathered from the code
that owns each part; ``domain/dataflow_block.py`` writes it.

Who gets it: a chat run that can write a node's code (:func:`writes_code`)
reads it before the canvas context, and a delegated run that writes code
(:data:`CODE_CAPABILITIES`) before its task. Each part is read the way the
Tools panel and a node's run read it:

- the datasets: the Data Catalog's rows installed in the dataflow, its
  "Datasets in project", each with the line the catalog gives it;
- the models: the model packages the dataflow's lockfile names that the
  account holds, its "Models in project", each with its loader line;
- the keys: the account's Node code keys, by name, from API Settings;
- the template being written, for a run that writes one node's code: the
  node's template as the project's roster resolves it, its starter as the
  starters feed reads it, and the functions of the modules a node of it can
  import (``packages.template_for_writing``).

The Data Catalog is read as the request's account (:func:`read_datasets`). A
Solve job holds no request, so it reads the rows once when it starts
(``turns/grounding._solve_grounding_base``) and hands them on.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import dataflow_block as block
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)

#: The grant with which a chat run rewrites a node's content, its code included.
REWRITE_GRANT = "node.content.write"
#: The grant with which a chat run proposes a new node and its content.
CREATE_GRANT = "node.create"
#: The capabilities a delegated run writes code for: one node's content, or a package's.
CODE_CAPABILITIES = frozenset({"node.content.generate", *content.PACKAGE_AUTHORING_CAPABILITIES})
#: The capability whose run writes one node's code: its block holds that node's template.
NODE_CAPABILITY = "node.content.generate"


def writes_code(granted, manifest=None) -> bool:
    """Whether a chat run with these grants, of the agent *manifest* defines,
    can write a node's code: it holds :data:`REWRITE_GRANT`, or it holds
    :data:`CREATE_GRANT` and its agent composes no notes. An agent that
    declares ``content.NOTES_CAPABILITY``, as the Researcher does, places
    notes with ``node.create``, not code."""
    granted = set(granted or ())
    if REWRITE_GRANT in granted:
        return True
    notes = content.NOTES_CAPABILITY in (getattr(manifest, "capability_ids", None) or [])
    return CREATE_GRANT in granted and not notes


def message(text: str) -> dict:
    """The block as the message a run reads: a user turn, as the canvas context is."""
    return {"role": "user", "content": text}


# --- The parts ---------------------------------------------------------------------


def datasets_in(items) -> tuple[block.Dataset, ...]:
    """The rows of a Data Catalog listing read for a dataflow that the
    dataflow has installed, each with the line the catalog gives it."""
    from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet

    rows = []
    for item in items or ():
        if not isinstance(item, dict) or not item.get("installed") or not item.get("id"):
            continue
        snippet = item.get("loaderSnippet")
        if not (isinstance(snippet, dict) and isinstance(snippet.get("code"), str) and snippet["code"].strip()):
            snippet = loader_snippet(item.get("format") or "", item.get("path"), dataset_id=item["id"])
        rows.append(block.Dataset(id=str(item["id"]), title=str(item.get("title") or item["id"]),
                                  format=str(item.get("format") or ""), loader=snippet["code"]))
    return tuple(rows)


def read_datasets(project_id: str, user=None) -> tuple[block.Dataset, ...]:
    """The dataflow's datasets (:func:`datasets_in`), from the Data Catalog as
    *user* reads it, the request's account when None. A catalog that cannot
    be read is no rows, logged."""
    try:
        from flask import g, has_request_context

        from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

        if user is None and has_request_context():
            user = getattr(g, "user", None)
        listing = DatasetCatalogService(user).list_catalog(dataflow_id=project_id)
    except Exception:  # noqa: BLE001 - a broken catalog leaves the block without datasets
        log.warning("Could not read the Data Catalog for project %s's dataflow block", project_id, exc_info=True)
        return ()
    return datasets_in((listing or {}).get("items"))


def _models(user_key: str, project_id: str) -> tuple[block.Model, ...]:
    """The model packages the dataflow's lockfile names that the account holds."""
    from utk_curio.backend.app.packages import service as packages_services

    try:
        lockfile = packages_services.get_project_lockfile(user_key, project_id)
        held = packages_services.held_model_packages(user_key)
    except Exception:  # noqa: BLE001 - an unreadable lockfile or store leaves the block without models
        log.warning("Could not read project %s's models for its dataflow block", project_id, exc_info=True)
        return ()
    return tuple(
        block.Model(id=h.manifest.package_id, name=h.manifest.name,
                    loader=packages_services.model_loader_line(h.manifest.package_id))
        for h in held if h.folder.name in lockfile
    )


def _keys(user_key: str) -> tuple[block.Key, ...]:
    """The account's Node code keys: name, host and delivery, never a value."""
    from utk_curio.backend.app.users.connection_keys import default_store

    try:
        refs = default_store().list(user_key)
    except Exception:  # noqa: BLE001 - an unreadable store is no keys
        return ()
    return tuple(block.Key(name=ref.name, host=ref.host, delivery=ref.delivery,
                           use=source_grounding.SecretRef(ref.name, ref.host, ref.delivery).use_line)
                 for ref in refs)


def _template(user_key: str, project_id: str, node_type: object) -> block.Template | None:
    from utk_curio.backend.app.packages import service as packages_services

    if not isinstance(node_type, str) or not node_type:
        return None
    try:
        found = packages_services.template_for_writing(user_key, project_id, node_type)
    except Exception:  # noqa: BLE001 - an unreadable template leaves the block without it
        log.warning("Could not read template %s for a dataflow block", node_type, exc_info=True)
        return None
    if found is None:
        return None
    functions = tuple(
        block.Function(module=row["module"], name=f["name"], call=f["call"], doc=f.get("doc") or "")
        for row in found["functions"] for f in row["functions"]
    )
    return block.Template(id=found["id"], label=found["label"], description=found["description"],
                          starter=found["starter"], language=found["language"], functions=functions)


# --- The block -------------------------------------------------------------------


def compose(
    user_key: str,
    project_id: str,
    *,
    node_type: object = None,
    datasets=None,
    tools=(),
    user=None,
) -> str | None:
    """The block for a run of *project_id* that writes code: the one place a
    run's block is composed. *node_type* is the type of the node it writes,
    if one; *datasets* the dataflow's rows when the caller read them already
    (a Solve job), else they are read now as *user*; *tools* the run's grants,
    of which the cut list names only those it holds. None when the block would
    hold nothing."""
    rows = read_datasets(project_id, user) if datasets is None else tuple(datasets)
    return block.layout(
        datasets=rows,
        models=_models(user_key, project_id),
        keys=_keys(user_key),
        template=_template(user_key, project_id, node_type),
        tools=tools,
    )


def node_type_of(spec: dict | None, node_id: object) -> str | None:
    """The type of the node *node_id* of *spec*, or None."""
    for node in ((spec or {}).get("dataflow") or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("id") == node_id:
            node_type = node.get("type")
            return node_type if isinstance(node_type, str) and node_type else None
    return None


def for_chat_run(
    user_key: str, project_id: str, spec: dict | None, target, granted, *, manifest=None, datasets=None,
) -> str | None:
    """The block of a chat run with these grants, of the agent *manifest*
    defines, on *target*, or None for a run that cannot write a node's code
    (:func:`writes_code`). On a node, its template is the one being written.
    *datasets*, the dataflow's rows when the turn read them already
    (:func:`read_datasets`), spare a second read."""
    if not writes_code(granted, manifest):
        return None
    node_id = target.get("targetId") if isinstance(target, dict) and target.get("kind") == "node" else None
    return compose(user_key, project_id, node_type=node_type_of(spec, node_id), datasets=datasets, tools=granted)


def named_node_type(inputs: dict | None, read_spec) -> str | None:
    """The type of the node a delegated run's *inputs* name: its ``nodeType``,
    its ``nodeContext.nodeType``, or the type of its ``nodeId`` in the spec
    *read_spec* returns, read only then. None when they name none."""
    inputs = inputs if isinstance(inputs, dict) else {}
    context = inputs.get("nodeContext") if isinstance(inputs.get("nodeContext"), dict) else {}
    node_type = inputs.get("nodeType") or context.get("nodeType")
    if not node_type and isinstance(inputs.get("nodeId"), str):
        node_type = node_type_of(read_spec(), inputs["nodeId"])
    return node_type if isinstance(node_type, str) and node_type else None


def for_delegated_run(
    user_key: str, project_id: str, capability: str, inputs: dict | None, *, datasets=None, user=None,
) -> str | None:
    """The block of a delegated run of *capability* with *inputs*, or None for
    a run that writes no code. A run that writes one node's code writes for
    the node its inputs name (:func:`named_node_type`). A delegated run holds
    no tool, so the cut list names none."""
    if capability not in CODE_CAPABILITIES:
        return None
    node_type = None
    if capability == NODE_CAPABILITY:
        node_type = named_node_type(inputs, lambda: projects_storage.read_spec(user_key, project_id))
    return compose(user_key, project_id, node_type=node_type, datasets=datasets, user=user)
