"""The catalog row contract.

``CatalogItem`` documents the dict shape produced by
``domain.catalog_item.base_item`` and returned throughout the catalog API. It is
a ``total=False`` TypedDict: it is a *documentation and type-checking aid only* —
the catalog pipeline continues to pass plain ``dict[str, Any]`` at runtime, and
several keys (``dirName``, ``needsReinstall``) are added dynamically by listing
and install flows rather than by ``base_item``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CatalogItem(TypedDict, total=False):
    # Identity / display
    id: str
    title: str
    fileName: str | None
    description: str
    sourceLabel: str

    # Classification / location
    origin: str  # imported | hub | computed | installed
    format: str
    uri: str
    path: str | None

    # Size / shape
    sizeBytes: int | None
    rowCount: int | None
    featureCount: int | None

    # Provenance (resolved across the user's projects by get_dataset/list_catalog)
    producerNodeId: str | None
    producerNodeType: str | None
    producerDataflowId: str | None
    producerDataflowName: str | None
    consumerNodeIds: list[str]
    consumerNodeCount: int

    # Metadata
    updatedAt: str
    license: str | None
    tags: list[str]
    schema: Any | None
    loaderSnippet: dict[str, Any] | None

    # State (set by listing / install flows, not by base_item)
    installed: bool
    dirName: str
    needsReinstall: bool

    # Grouping for multi-part imports (OSM PBF layers): sibling layer datasets
    # share ``groupId``; ``layerName`` is this dataset's layer. The synthetic
    # group item carries ``groupLayerIds`` (member dataset ids) instead.
    groupId: str | None
    layerName: str | None
    groupLayerIds: list[str]
