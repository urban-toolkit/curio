"""Where a model's files are, for one execution, and what its manifest says.

The backend resolves each ``curio_load_model("<id>")`` a node's code names to
the folder of the model package the running account's store holds
(``packages.service.resolve_model_dirs``), as it resolves
``curio_load_data``. Models behave like nodes: one the account never added
resolves to nothing. In process the folder is used where it is; under
isolation it is staged into the child's scratch directory first
(``staging.stage_model_dirs``) and the mapping names the staged folder.
``catalog_helpers.curio_load_model`` loads the model from that folder.

The folder's ``manifest.json`` is a model package's (kind ``model``, its
``model`` block naming the weights under ``models/``); :func:`model_spec` also
reads a flat manifest that names them itself.
"""

from __future__ import annotations

import os

#: What ``curio_load_model`` says of a model the backend gave the node no
#: folder for: one the account never added, or a model that ships with Curio
#: whose weights this Curio could not have (a pip install that could not
#: download them).
MISSING_MODEL = (
    "Model '{model_id}' is not one of your models: add it with Add in the Model Catalog, "
    "then run this node again. "
    "If it is a model that ships with Curio and you added it, this Curio could not give it to the node. "
    "A pip install downloads such a model's weights from GitHub the first time a node runs it, "
    "which needs this machine to reach raw.githubusercontent.com, and "
    "a clone of https://github.com/urban-toolkit/curio holds them in packages/."
)


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
            raise RuntimeError(MISSING_MODEL.format(model_id=model_id))
        return os.path.join(base, folder) if base else folder

    return model_folder
