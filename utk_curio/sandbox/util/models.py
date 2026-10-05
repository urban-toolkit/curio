"""Where a Model Catalog model's files are, for one execution.

The backend resolves each ``curio_load_model("<id>")`` a node's code names to
the model's folder for the account running it (``model_catalog.service``), as
it resolves ``curio_load_data``. In process the folder is used where it is;
under isolation it is staged into the child's scratch directory first
(``staging.stage_model_dirs``) and the mapping names the staged folder.
``catalog_helpers.curio_load_model`` loads the model from that folder.
"""

from __future__ import annotations

import os


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
