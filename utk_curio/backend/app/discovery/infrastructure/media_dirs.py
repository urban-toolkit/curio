"""Where a collection's derived files live, and who can reach them.

Two places, for two readers:

- ``media_cache_dir``: thumbnails, posters and spectrograms the backend draws
  and serves. Only the backend reads them, so they sit in the user's own store,
  ``.curio/users/<key>/media-cache/<datasetId>/``.
- ``media_work_dir``: files a node must read or write as well as the backend,
  a bucket collection's cached objects and the files a node derives from a
  collection's files (frames, videos, audio windows, overlays). Under fork
  isolation a node runs as the execution user and ``.curio/users`` is closed
  to it, so these sit in the user's execution scratch,
  ``.curio/exec-scratch/users/<key>/media/``, the one place an isolated node
  may write. With isolation off they sit in the user's store.

Every hosted guest signs in to one shared account, so what one guest's nodes
derive is kept in a folder of that guest's own in the account's media folder
(``derived_root``), named as their datasets are, and goes when the server
starts (``forget_visitors``).

A dashboard viewer's step runs as the dataflow's owner, so what it derives is
kept in a folder of the step's own in the owner's media folder
(``derived_root``'s *kept*), named after its kept session
(``kept_media_name``), and goes with the step's kept output
(``forget_kept``, ``runs/kept.py``): a viewer's run never writes where the
owner's runs write, and two viewers' runs never write in one folder.
"""

from __future__ import annotations

import contextlib
import hashlib
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


def cache_lock(user_key: str, dataset_id: str) -> Path:
    """The lock file a cache of one collection holds (``cache_collection``).

    In the account's own store, where no node reaches it: a node that could
    open it could hold it, and no cache of the collection would run again.
    Beside the collection's thumbnails, not among them, since
    :func:`forget_media` removes their folder.
    """
    folder = users_base() / user_key_segment(user_key) / "media-cache"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f".{_dataset_segment(dataset_id)}.cache.lock"


def room_files(user_key: str) -> tuple[Path, Path]:
    """The account's room in its media cache (``cache_collection.check_room``):
    the file of what its running caches and adds have still to land, and the
    lock it is read and written under. Beside the collections' cache locks,
    for the same reasons (:func:`cache_lock`)."""
    folder = users_base() / user_key_segment(user_key) / "media-cache"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / ".room.json", folder / ".room.lock"


def forget_media(user_key: str, dataset_id: str) -> None:
    """Remove what Curio made from one dataset's files: its thumbnails, its
    cached bucket files, and the files nodes derived from it, in the media
    folder, in each visitor's own folder in it and in each dashboard viewer's
    step's (:func:`derived_root`).

    Never the files themselves, which are the source's.
    """
    import shutil

    from utk_curio.sandbox.util.collections import DERIVED, KEPT_MEDIA

    segment = _dataset_segment(dataset_id)
    key = user_key_segment(user_key)
    root = media_work_root(user_key)
    folders = [users_base() / key / "media-cache" / segment, root / "objects" / segment]
    roots = [root]
    for group in (VISITORS, KEPT_MEDIA):
        if (root / group).is_dir():
            roots += [folder for folder in (root / group).iterdir() if folder.is_dir()]
    derived = sorted({folder for types in DERIVED.values() for folder, _kind in types.values()})
    folders += [where / folder / segment for where in roots for folder in derived]
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


#: In the shared guest account's media folder: a folder of each hosted
#: guest's own, for the files their nodes derive (:func:`derived_root`).
VISITORS = "visitors"


def derived_root(user_key: str, visitor: str | None = None, *, kept: str | None = None) -> Path:
    """Where the files nodes derive from a collection's files are, without
    creating it: *user_key*'s media folder, or *visitor*'s own folder in it,
    ``<media>/visitors/<visitor>/``, for a hosted guest named as
    ``visitor_copies.visitor_of`` names them, never by the sign-in. *kept*,
    the name of a dashboard viewer's step's folder (:func:`kept_media_name`),
    is that step's own, ``<media>/kept/<kept>/``, whoever its run serves; a
    name of any other shape raises ValueError. A node makes the folder as it
    writes there, so under isolation it is the execution user's."""
    root = media_work_root(user_key)
    if kept is not None:
        from utk_curio.sandbox.util.collections import KEPT_MEDIA, KEPT_NAME_RE

        if not isinstance(kept, str) or not KEPT_NAME_RE.match(kept):
            raise ValueError("not the folder of a dashboard viewer's step")
        return root / KEPT_MEDIA / kept
    if not visitor:
        return root
    return root / VISITORS / validate_component(visitor, field="visitor")


def kept_media_name(session_id: str) -> str:
    """The name of the folder of the dashboard viewer's step that runs in the
    kept session *session_id* (:func:`derived_root`): a digest of the
    session, never the session itself, since the URLs of the rows the step
    derives name the folder (``collections.KEPT_NAME_RE``)."""
    return "k" + hashlib.sha256(f"curio-kept-media:{session_id}".encode("utf-8")).hexdigest()[:32]


def forget_kept(user_key: str, names) -> None:
    """Remove the folders *names* of dashboard viewers' steps
    (:func:`kept_media_name`) in *user_key*'s media folder, with what the
    steps derived: their kept outputs went, or the step kept none
    (``runs/kept.py``, ``runs/viewer.py``)."""
    import shutil

    for name in names or ():
        try:
            folder = derived_root(user_key, kept=name)
        except ValueError:
            continue
        shutil.rmtree(folder, ignore_errors=True)


def forget_visitors(user_key: str) -> None:
    """Remove every visitor's own folder in *user_key*'s media folder, with
    what their nodes derived: the server does when it starts
    (``visitor_copies.drop_all``)."""
    import shutil

    shutil.rmtree(media_work_root(user_key) / VISITORS, ignore_errors=True)


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
    with contextlib.suppress(OSError):
        while True:
            os.chown(current, uid, -1)
            if current == stop or current.parent == current:
                break
            current = current.parent
