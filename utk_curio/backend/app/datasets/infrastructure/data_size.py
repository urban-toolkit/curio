"""The size the Data Catalog gives a dataset.

A dataset's size is the bytes of its data file, the manifest's ``dataFile``,
except for a bundle (``format: bundle``). A bundle's ``dataFile`` is
``data/bundle.json``, an index of the parts the bundle holds, and its size is
the bytes of the parts that index lists (#1060). Neither the index nor the
files read beside a part (a parquet's ``.decode.json``) count.
"""

from __future__ import annotations

from pathlib import Path
from stat import S_ISREG


def data_size_bytes(fmt: str | None, data_path: Path) -> int | None:
    """The bytes of the dataset in the format *fmt* whose data file is
    *data_path*, or None when there are none to count.

    None when *data_path* is not a regular file: a re-install removes a
    computed dataset's folder and writes it again, so its data file can go at
    any moment (#780), and a listing that finds it gone must still answer. A
    bundle counts the parts ``listed_bundle_parts`` gives, each stat'd once. A
    part removed since it was listed is left out, and a bundle with no part to
    count is None, a size not known.
    """
    try:
        info = data_path.stat()
    except (OSError, ValueError):
        return None
    if not S_ISREG(info.st_mode):
        return None
    if fmt != "bundle":
        return info.st_size
    # Imported here, as the backend's other readers of the sandbox's helpers do.
    from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts

    try:
        parts = listed_bundle_parts(data_path)
    except (OSError, ValueError):
        return None  # a part's name the file system refuses
    sizes = []
    for _part, file in parts:
        try:
            sizes.append(file.stat().st_size)
        except (OSError, ValueError):
            continue  # removed since it was listed
    return sum(sizes) if sizes else None
