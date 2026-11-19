"""A segmentation model's package, written into a store as the Discovery Catalog writes one.

The Hugging Face models source names the node a model it adds gets
(``provider.options.node``); a download copies that template from the shared
catalog, its source with its ``curio_load_model`` call naming the model, and
the packages its package names (``packages.service.model_node``).
:func:`install_downloaded_segmentation_model` installs a package of that
shape through the same install a download makes
(``packages.service.install_downloaded_model``), around a weights folder the
test gives.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
#: The source a download comes from.
HUGGING_FACE_MODELS = REPO / "discovery" / "source.huggingface.models@1" / "manifest.json"


def download_node():
    """The node the Hugging Face models source gives a model it adds, read
    from the shared catalog (``packages.service.ModelNode``)."""
    from utk_curio.backend.app.packages.service import model_node

    source = json.loads(HUGGING_FACE_MODELS.read_text(encoding="utf-8"))
    return model_node(source["provider"]["options"]["node"])


def install_downloaded_segmentation_model(user_key: str, files: Path, manifest: dict):
    """Install *manifest* (a model package's, with no templates) and the
    weights in *files*, which is consumed, into *user_key*'s store with the
    node, the source and the packages a download writes. Returns the
    installed manifest."""
    from utk_curio.backend.app.packages.service import install_downloaded_model

    node = download_node()
    dependencies = dict(manifest.get("dependencies") or {})
    dependencies["packages"] = {**dict(dependencies.get("packages") or {}), **node.packages}
    full = {**manifest, "dependencies": dependencies, "templates": [node.template]}
    return install_downloaded_model(
        user_key, files, full, sources={node.template["source"]: node.code_for(str(manifest["id"]))},
    )
