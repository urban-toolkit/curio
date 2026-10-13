"""Where a model's files are, for one execution, and what its manifest says.

The backend resolves each ``curio_load_model("<id>")`` a node's code names to
the model's folder for the account running it (``packages.service
.resolve_model_dirs`` for a model package, else ``model_catalog.service``), as
it resolves ``curio_load_data``. In process the folder is used where it is;
under isolation it is staged into the child's scratch directory first
(``staging.stage_model_dirs``) and the mapping names the staged folder.
``catalog_helpers.curio_load_model`` loads the model from that folder.

The folder's ``manifest.json`` is a model package's (kind ``model``, its
``model`` block naming the weights under ``models/``) or a Model Catalog
model's; :func:`model_spec` reads both the same way.
"""

from __future__ import annotations

import os


def model_spec(manifest: dict) -> dict:
    """How to run the model *manifest* describes, as one flat dict: ``runtime``,
    ``task``, ``entry`` (relative to the manifest's folder), ``labels`` and
    ``input``. A model package's ``model`` block names its kind of model
    ``type``, which is read as ``task``."""
    if not isinstance(manifest, dict):
        return {}
    if manifest.get("kind") != "model":
        return manifest
    block = manifest.get("model") if isinstance(manifest.get("model"), dict) else {}
    return {**block, "id": manifest.get("id"), "task": block.get("type")}


def make_model_folder(models, *, base=None):
    """``model_folder(model_id)`` over *models* (``{id: folder}``).

    *base* is the folder a staged name is relative to (the scratch directory
    of an isolated child); None when the folders are absolute.
    """
    known = {str(k): str(v) for k, v in (models or {}).items()}

    def model_folder(model_id):
        model_id = str(model_id)
        folder = known.get(model_id)
        if folder is None:
            raise RuntimeError(
                f"Model '{model_id}' is not available in this environment - "
                "drag a model from the Model Catalog onto this node, then run it again."
            )
        return os.path.join(base, folder) if base else folder

    return model_folder
