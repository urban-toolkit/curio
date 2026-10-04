"""Which node outputs a run saves, decided as the canvas decides it.

The Python twin of ``utils/saveOutputDataset.ts``, reading nodes the way a
saved dataflow holds them: ``saveOutputDataset`` on the node itself and
``datasetSource`` under ``metadata``. Two decisions, as on the canvas:

- :func:`should_save_output_on_run` is ``shouldSaveOutputOnRun``: whether a
  run auto-installs the node's output in the Data Catalog.
- :func:`records_output_on_save` is the per-node rule of
  ``buildSaveableLiveOutputs``: whether the output is recorded in the
  dataflow's outputs, so a reload restores it.

``utils/saveOutputDataset.cases.json`` in the frontend holds the cases both
sides run. The set of nodes feeding a pinned dashboard tile is an argument,
as it is in TypeScript.
"""
from __future__ import annotations

from typing import Collection, Optional


def _default(default_save: Optional[bool]) -> bool:
    if default_save is not None:
        return bool(default_save)
    from utk_curio.backend.config import CURIO_DEFAULT_SAVE_NODE_OUTPUT

    return bool(CURIO_DEFAULT_SAVE_NODE_OUTPUT)


def is_dataset_palette_node(node: dict) -> bool:
    """A node a dataset was dragged in as: it loads an installed dataset."""
    metadata = (node or {}).get("metadata") or {}
    source = metadata.get("datasetSource") if isinstance(metadata, dict) else None
    return bool(isinstance(source, dict) and source.get("datasetId"))


def resolve_save_output_dataset(node: dict, default_save: Optional[bool] = None) -> bool:
    """The node's Save toggle, or the default when it has none. Always off for a
    dataset-palette node, whose output is the dataset it reads."""
    if is_dataset_palette_node(node):
        return False
    flag = (node or {}).get("saveOutputDataset")
    if isinstance(flag, bool):
        return flag
    return _default(default_save)


def should_save_output_on_run(
    node: dict,
    default_save: Optional[bool] = None,
    is_dashboard_source: bool = False,
) -> bool:
    """Whether running *node* auto-installs its output (``shouldSaveOutputOnRun``)."""
    if is_dataset_palette_node(node):
        return False
    return resolve_save_output_dataset(node, default_save) or bool(is_dashboard_source)


def records_output_on_save(
    node: dict,
    default_save: Optional[bool] = None,
    dashboard_sources: Collection[str] = (),
) -> bool:
    """Whether *node*'s output is recorded in the dataflow's outputs.

    Never for a visualization sink, which passes its input through. Always for
    a node feeding a pinned dashboard tile, a dataset-palette node included.
    Otherwise the node's Save toggle or the default.
    """
    from utk_curio.backend.app.projects.services import _is_sink_node_type

    node = node or {}
    if _is_sink_node_type(node.get("type")):
        return False
    if node.get("id") in dashboard_sources:
        return True
    return resolve_save_output_dataset(node, default_save)
