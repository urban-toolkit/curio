from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, List

VALID_ACCENTS = {"peach", "sky", "mint", "lilac"}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower().strip())
    return re.sub(r"[\s_-]+", "-", slug)[:240]


@dataclass
class OutputRef:
    node_id: str
    filename: str
    # Sandbox ``dataType`` (e.g. raster, dataframe) for extensionless DuckDB paths.
    data_type: Optional[str] = None
    # Producing node's friendly display label, resolved client-side. The save-time
    # installer titles the computed dataset with it instead of the raw generated
    # filename (see ``_auto_install_computed_outputs``).
    node_name: Optional[str] = None


@dataclass
class ProjectCreate:
    name: str
    spec: dict
    outputs: List[OutputRef] = field(default_factory=list)
    description: Optional[str] = None
    thumbnail_accent: str = "peach"

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("name is required")
        if self.thumbnail_accent not in VALID_ACCENTS:
            self.thumbnail_accent = "peach"
        self.outputs = [
            OutputRef(**o) if isinstance(o, dict) else o for o in self.outputs
        ]


@dataclass
class ProjectUpdate:
    spec: Optional[dict] = None
    outputs: Optional[List[OutputRef]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    thumbnail_accent: Optional[str] = None

    def __post_init__(self):
        if self.thumbnail_accent and self.thumbnail_accent not in VALID_ACCENTS:
            self.thumbnail_accent = None
        if self.outputs is not None:
            self.outputs = [
                OutputRef(**o) if isinstance(o, dict) else o for o in self.outputs
            ]


@dataclass
class ProjectSummary:
    id: str
    name: str
    slug: str
    description: Optional[str]
    thumbnail_accent: str
    spec_revision: int
    last_opened_at: Optional[str]
    created_at: str
    updated_at: str
    archived_at: Optional[str] = None
    graph_preview: Optional[dict] = None


@dataclass
class ProjectDetail(ProjectSummary):
    folder_path: str = ""
    spec: Optional[dict] = None
    outputs: List[OutputRef] = field(default_factory=list)
    # Computed outputs that could NOT be auto-installed on this save (e.g. the
    # artifact was missing at save time). Response-only, never persisted — lets
    # the client warn the user about a silently-skipped dataset.
    dataset_install_warnings: List[dict] = field(default_factory=list)


@dataclass
class SaveBody:
    name: str
    spec: dict
    outputs: List[OutputRef] = field(default_factory=list)
    description: Optional[str] = None
    thumbnail_accent: str = "peach"


@dataclass
class LoadResponse:
    project: ProjectDetail
    spec: dict
    outputs: List[OutputRef] = field(default_factory=list)
