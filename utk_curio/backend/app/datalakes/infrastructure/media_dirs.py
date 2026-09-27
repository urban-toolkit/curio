"""Where a collection's derived files live, and who can reach them.

Two places, for two readers:

- ``media_cache_dir``: thumbnails, posters and spectrograms the backend draws
  and serves. Only the backend reads them, so they sit in the user's own store,
  ``.curio/users/<key>/media-cache/<datasetId>/``.
- ``media_work_dir``: files a node must read or write as well as the backend,
  a bucket collection's cached objects and the frames or audio windows a node
  extracts. Under fork isolation a node runs as the execution user and
  ``.curio/users`` is closed to it, so these sit in the user's execution
  scratch, ``.curio/exec-scratch/users/<key>/media/``, the one place an
  isolated node may write. With isolation off they sit in the user's store.
"""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import validate_component
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base


def isolation_on() -> bool:
    """Whether node code runs forked as the execution user."""
    return (os.environ.get("CURIO_ISOLATION") or "").strip().lower() == "fork"


def _exec_uid() -> int | None:
    user = (os.environ.get("CURIO_EXEC_USER") or "").strip()
    if not user or not hasattr(os, "getuid") or os.getuid() != 0:
        return None
    try:
        import pwd

        return pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None


def _dataset_segment(dataset_id: str) -> str:
    return validate_component(dataset_id, field="dataset id")


def media_cache_dir(user_key: str, dataset_id: str) -> Path:
    path = users_base() / user_key_segment(user_key) / "media-cache" / _dataset_segment(dataset_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def forget_media(user_key: str, dataset_id: str) -> None:
    """Remove what Curio made from one dataset's files: its thumbnails, its
    cached bucket files, and the frames and clips nodes derived from it.

    Never the files themselves, which are the source's.
    """
    import shutil

    from utk_curio.sandbox.util.collections import DERIVED

    segment = _dataset_segment(dataset_id)
    key = user_key_segment(user_key)
    folders = [users_base() / key / "media-cache" / segment, media_work_root(user_key) / "objects" / segment]
    folders += [media_work_root(user_key) / folder / segment for folder, _ext, _kind in DERIVED.values()]
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


def media_work_root(user_key: str) -> Path:
    """The user's shared media directory, without creating it."""
    key = user_key_segment(user_key)
    if isolation_on():
        from utk_curio.sandbox.isolation.supervisor import user_work_dir

        shared = os.environ.get("CURIO_SHARED_DATA") or str(users_base().parent / "data")
        return Path(user_work_dir(shared, key)) / "media"
    return users_base() / key / "media"


def media_work_dir(user_key: str, *parts: str) -> Path:
    """``media_work_root(user_key)/<parts...>``, created, and reachable by a
    node when isolation is on."""
    path = media_work_root(user_key)
    for part in parts:
        path = path / validate_component(part, field="media folder")
    path.mkdir(parents=True, exist_ok=True)
    grant_to_child(path, up_to=media_work_root(user_key).parent)
    return path


def grant_to_child(path: Path, *, up_to: Path | None = None) -> None:
    """Hand *path* (and its parents below *up_to*) to the execution user.

    A no-op unless this process is root with an execution user to hand it to,
    which is exactly the isolated deployment's shape.
    """
    uid = _exec_uid()
    if uid is None:
        return
    current = Path(path)
    stop = Path(up_to) if up_to else current
    try:
        while True:
            os.chown(current, uid, -1)
            if current == stop or current.parent == current:
                break
            current = current.parent
    except OSError:
        pass
