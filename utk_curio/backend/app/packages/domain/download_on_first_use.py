"""``downloadOnFirstUse``: the files of a shipped dataset or model package that the pip package leaves out.

PyPI takes no file over 100 MiB, so the release leaves the catalogs' biggest
files out of the pip package (``setup.py``), and a pip install downloads each
from GitHub the first time Curio needs it
(``datasets/infrastructure/left_out_files.py``). The manifest of a dataset or
of a model package names them, by their paths in its folder; a folder's path
covers every file in it.

Both catalogs' manifest readers check the field here, so they read it alike;
each then holds it to the files its readers download: a dataset's data file,
a model package's weights.
"""

from __future__ import annotations

FIELD = "downloadOnFirstUse"
#: The files every catalog folder ships: a pip install reads the manifest to
#: know what to download, and a package's integrity.json to check it.
ALWAYS_SHIPPED = ("manifest.json", "integrity.json")


class DownloadOnFirstUseError(ValueError):
    """A ``downloadOnFirstUse`` that cannot be read; the message says where and why."""


def clean_download_on_first_use(raw: object, *, where: str) -> tuple[str, ...]:
    """The paths *raw* names: a list of distinct paths inside the folder,
    with ``/`` between their parts, none of them empty, ``.`` or ``..``, and
    none of :data:`ALWAYS_SHIPPED`. Absent (``None``) names none."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DownloadOnFirstUseError(f"{where} must be a list of paths in the folder")
    paths: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not _inside_the_folder(value):
            raise DownloadOnFirstUseError(
                f"{where}: {value!r} is not a path inside the folder "
                "(its parts joined by '/', none of them empty, '.' or '..')"
            )
        if value in ALWAYS_SHIPPED:
            raise DownloadOnFirstUseError(f"{where}: {value} always ships, since a pip install reads it")
        if value in paths:
            raise DownloadOnFirstUseError(f"{where} names {value} twice")
        paths.append(value)
    return tuple(paths)


def _inside_the_folder(path: str) -> bool:
    return (
        not path.startswith("/")
        and "\\" not in path
        and all(part not in ("", ".", "..") for part in path.split("/"))
    )
