"""Files a node saves from its code into its dataflow's Computed datasets.

``curio_save_file("summary.csv")`` and ``curio_save_folder("tiles")`` save
under a name, and ``curio_computed_path("summary")`` reads it back, in nodes
of the same dataflow (``sandbox/util/saved_files.py``). The dataset is
``computed.<dataflowId>.files.<name>``: the dataflow id comes from the run,
never from the code, and the ``files`` segment keeps these ids apart from a
node's own saved output, ``computed.<dataflowId>.<nodeId>``.

The name rule and the file formats are the sandbox's twins, kept in step by
``test_saved_files.py``.
"""

from __future__ import annotations

import re

#: The segment between the dataflow and the name.
FILES_SEGMENT = "files"

#: A saved name, one id segment (``sandbox/util/saved_files.NAME_RE``).
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

#: The extension a saved file has, and the dataset format it is stored as
#: (``sandbox/util/saved_files.FILE_FORMATS``).
FILE_FORMATS = {
    "csv": "csv",
    "json": "json",
    "geojson": "geojson",
    "parquet": "parquet",
    "tif": "geotiff",
    "tiff": "geotiff",
    "nc": "netcdf",
}

#: Where a saved folder's files sit under its dataset's ``data/``.
FOLDER_FILES = "files"

#: Literal ``curio_computed_path("<name>")`` calls: the saved names a node reads.
COMPUTED_PATH_CALL_RE = re.compile(r"""curio_computed_path\(\s*(["'])([a-z][a-z0-9-]{0,62})\1\s*\)""")

#: Literal ``curio_save_file("<name>.<ext>")`` and ``curio_save_folder("<name>")``
#: calls: the names a node saves.
SAVE_CALL_RE = re.compile(
    r"""curio_save_(?:file|folder)\(\s*(["'])([a-z][a-z0-9-]{0,62})(?:\.[A-Za-z0-9]{1,8})?\1\s*\)"""
)

#: The most saved names one node's code reads.
MAX_COMPUTED_NAMES = 16


def computed_names_in_code(code: object) -> list[str]:
    """The names *code* reads with literal ``curio_computed_path`` calls, in order."""
    if not isinstance(code, str) or "curio_computed_path" not in code:
        return []
    names: list[str] = []
    for match in COMPUTED_PATH_CALL_RE.finditer(code):
        if match.group(2) not in names:
            names.append(match.group(2))
        if len(names) >= MAX_COMPUTED_NAMES:
            break
    return names


def saved_names_in_code(code: object) -> list[str]:
    """The names *code* saves with literal ``curio_save_file`` / ``curio_save_folder`` calls."""
    if not isinstance(code, str) or "curio_save_" not in code:
        return []
    names: list[str] = []
    for match in SAVE_CALL_RE.finditer(code):
        if match.group(2) not in names:
            names.append(match.group(2))
    return names
