"""Where a collection's derived files live, and who can reach them.

Two places, for two readers:

- ``media_cache_dir``: thumbnails, posters and spectrograms the backend draws
  and serves. Only the backend reads them, so they sit in the user's own store,
  ``.curio/users/<key>/media-cache/<datasetId>/``, those of a run's files in a
  folder named after the run's (``<datasetId>/<name>/``).
- ``media_work_dir``: files a node must read or write as well as the backend,
  a bucket collection's cached objects and the files a node derives from a
  collection's files (frames, videos, audio windows, overlays). Under fork
  isolation a node runs as the execution user and ``.curio/users`` is closed
  to it, so these sit in the user's execution scratch,
  ``.curio/exec-scratch/users/<key>/media/``, the one place an isolated node
  may write. With isolation off they sit in the user's store.

Every run derives in a folder of its own, ``<media>/kept/<name>/``
(:func:`derived_root`), named after its kept session or a fresh one
(:func:`kept_media_name`), which the URLs of the rows it derives name: no two
runs write one file, whoever made them. Every hosted guest signs in to one
shared account, so a run that serves a hosted guest derives in a folder of
that guest's own, ``<media>/visitors/<visitor>/kept/<name>/``, named as their
datasets are, which goes when the server starts (:func:`forget_visitors`). A
dashboard viewer's step derives in the account's, whoever it serves: its kept
output serves every visitor.

A run's folder goes once no kept output and no saved output names it
(:func:`forget_kept`, ``runs/kept.py``), or once nothing has been written in
it for the days a kept output lives when nothing ever named it
(``kept.sweep_kept_media``), and its thumbnails go with it.
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
    cached bucket files, and the files nodes derived from it, in the folder of
    each derived row's kind (``DERIVED_FOLDERS``) in every run's folder, the
    account's and each hosted guest's (:func:`derived_root`).

    Never the files themselves, which are the source's.
    """
    import shutil

    from utk_curio.sandbox.util.collections import DERIVED_FOLDERS

    segment = _dataset_segment(dataset_id)
    key = user_key_segment(user_key)
    root = media_work_root(user_key)
    folders = [users_base() / key / "media-cache" / segment, root / "objects" / segment]
    derived = sorted(set(DERIVED_FOLDERS.values()))
    folders += [run / folder / segment for run in _run_folders(root) for folder in derived]
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
#: guest's own, holding the folders of the runs that serve them
#: (:func:`derived_root`).
VISITORS = "visitors"


def derived_root(user_key: str, visitor: str | None = None, *, kept: str) -> Path:
    """The folder of one run's own, where it writes the files it derives from
    a collection's files, without creating it: ``<media>/kept/<kept>/`` in
    *user_key*'s media folder, or in *visitor*'s own folder in it,
    ``<media>/visitors/<visitor>/kept/<kept>/``, for a run that serves a
    hosted guest, named as ``visitor_copies.visitor_of`` names them, never by
    the sign-in. *kept* is the folder's name (:func:`kept_media_name`); a name
    of any other shape raises ValueError. A node makes the folder as it writes
    there, so under isolation it is the execution user's."""
    from utk_curio.sandbox.util.collections import KEPT_MEDIA, KEPT_NAME_RE

    if not isinstance(kept, str) or not KEPT_NAME_RE.match(kept):
        raise ValueError("not the name of a run's folder")
    root = media_work_root(user_key)
    if visitor:
        root = root / VISITORS / validate_component(visitor, field="visitor")
    return root / KEPT_MEDIA / kept


def kept_media_name(session_id: str) -> str:
    """The name of the folder of the run in the session *session_id*
    (:func:`derived_root`): its kept session, or a session made for it alone
    when it keeps none (``node_exec``, ``exec_collections.media_dir_for``). A
    digest of the session, never the session itself, since the URLs of the
    rows the run derives name the folder (``collections.KEPT_NAME_RE``)."""
    return "k" + hashlib.sha256(f"curio-kept-media:{session_id}".encode("utf-8")).hexdigest()[:32]


def _homes(media: Path) -> list[Path]:
    """The folders of the media folder *media* that hold runs' folders: its
    own, and each hosted guest's (:data:`VISITORS`)."""
    homes = [media]
    visitors = media / VISITORS
    if visitors.is_dir():
        homes += [folder for folder in visitors.iterdir() if folder.is_dir()]
    return homes


def _run_folders(media: Path):
    """Every run's folder in the media folder *media*, the account's and
    each hosted guest's (:func:`derived_root`)."""
    from utk_curio.sandbox.util.collections import KEPT_MEDIA, KEPT_NAME_RE

    for home in _homes(media):
        kept = home / KEPT_MEDIA
        if not kept.is_dir():
            continue
        for folder in kept.iterdir():
            if folder.is_dir() and KEPT_NAME_RE.match(folder.name):
                yield folder


def forget_kept(user_key: str, names) -> None:
    """Remove the runs' folders *names* (:func:`kept_media_name`) in
    *user_key*'s media folder, the account's and each hosted guest's of each
    name, with what the runs derived and the thumbnails drawn of it
    (``media.thumbnail``): no kept output and no saved output names them any
    more, or their run kept none (``runs/kept.py``)."""
    import shutil

    from utk_curio.sandbox.util.collections import KEPT_MEDIA, KEPT_NAME_RE

    wanted = sorted({name for name in names or () if isinstance(name, str) and KEPT_NAME_RE.match(name)})
    if not wanted:
        return
    for home in _homes(media_work_root(user_key)):
        for name in wanted:
            shutil.rmtree(home / KEPT_MEDIA / name, ignore_errors=True)
    cache = users_base() / user_key_segment(user_key) / "media-cache"
    if cache.is_dir():
        for dataset in cache.iterdir():
            if dataset.is_dir():
                for name in wanted:
                    shutil.rmtree(dataset / name, ignore_errors=True)


def _media_roots():
    """``(account, media folder)`` of every account's media folder there is
    (:func:`media_work_root`): *account* is its storage key."""
    if isolation_on():
        from utk_curio.sandbox.isolation.supervisor import user_work_dir

        shared = os.environ.get("CURIO_SHARED_DATA") or str(users_base().parent / "data")
        accounts = Path(user_work_dir(shared, "_")).parent
    else:
        accounts = users_base()
    if not accounts.is_dir():
        return
    for account in accounts.iterdir():
        media = account / "media"
        if media.is_dir():
            yield account.name, media


def run_folders():
    """``(account, folder)`` of every run's folder there is, in every
    account's media folder, the hosted guests' among them
    (:func:`derived_root`), for the sweep of those nothing names
    (``kept.sweep_kept_media``); *account* is the storage key of the account
    whose media folder holds it."""
    for account, media in _media_roots():
        for folder in _run_folders(media):
            yield account, folder


def forget_gone_runs_thumbnails() -> int:
    """Remove the thumbnails of every run's folder that is gone, in every
    account's media cache (``media-cache/<datasetId>/<name>/``,
    ``media.thumbnail``), however it went: the start's drop of the hosted
    guests' folders, a dataflow's delete, a sweep. Returns how many folders
    of thumbnails went."""
    import shutil

    from utk_curio.sandbox.util.collections import KEPT_NAME_RE

    base = users_base()
    if not base.is_dir():
        return 0
    gone = 0
    for account in base.iterdir():
        cache = account / "media-cache"
        if not cache.is_dir():
            continue
        try:
            media = media_work_root(account.name)
        except ValueError:
            continue
        live = {folder.name for folder in _run_folders(media)} if media.is_dir() else set()
        for dataset in cache.iterdir():
            if not dataset.is_dir():
                continue
            for folder in dataset.iterdir():
                if folder.is_dir() and KEPT_NAME_RE.match(folder.name) and folder.name not in live:
                    shutil.rmtree(folder, ignore_errors=True)
                    gone += 1
    return gone


def folder_bytes(folder) -> int:
    """The bytes of the files in *folder*, every level down; 0 for no folder."""
    total = 0
    path = Path(folder) if folder else None
    if path is None or not path.is_dir():
        return 0
    for item in path.rglob("*"):
        with contextlib.suppress(OSError):
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
    return total


def run_folder_beside(media_dir: str | None) -> str | None:
    """A fresh run's folder beside the run's folder *media_dir*, in the same
    account's or hosted guest's media folder (:func:`derived_root`), for one
    more run of the same caller: each node of a slice that Solve or an agent
    runs (``runner.run_through_node``). *media_dir* itself when it is no
    run's folder, which ``curio_derived_file`` refuses."""
    from utk_curio.common.kept_sessions import new_session_id
    from utk_curio.sandbox.util.collections import kept_of

    if not kept_of(media_dir):
        return media_dir
    return str(Path(media_dir).parent / kept_media_name(new_session_id()))


def _link_or_copy(source, target):
    """*target* as a second name of *source*'s file, or a copy of it where
    the two cannot share one (another filesystem): a run writes its files
    once, so a link is safe."""
    import shutil

    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return target


def link_runs(source_key: str, target_key: str, names) -> list[str]:
    """Put the account *source_key*'s runs' folders *names* in the account
    *target_key*'s media folder under the same names, their files linked, not
    copied (:func:`_link_or_copy`), and the folders handed to the execution
    user (:func:`grant_to_child`): Save a copy into another account brings
    the files its saved outputs name (``projects/services``). A folder the
    source no longer holds, or the target already does, is left out. The
    names it put in place."""
    import shutil

    from utk_curio.sandbox.util.collections import KEPT_NAME_RE

    placed = []
    for name in sorted({name for name in names or () if isinstance(name, str) and KEPT_NAME_RE.match(name)}):
        source, target = derived_root(source_key, kept=name), derived_root(target_key, kept=name)
        if not source.is_dir() or target.exists():
            continue
        shutil.copytree(source, target, copy_function=_link_or_copy, symlinks=False)
        for folder in [target, *(path for path in target.rglob("*") if path.is_dir())]:
            grant_to_child(folder, up_to=media_work_root(target_key).parent)
        placed.append(name)
    return placed


def last_written(folder: Path) -> float:
    """When anything in *folder*, or the folder itself, was last written: a
    step writes deep in its folder, which leaves the folder's own time alone."""
    newest = folder.stat().st_mtime
    for path in folder.rglob("*"):
        with contextlib.suppress(OSError):
            newest = max(newest, path.stat().st_mtime)
    return newest


def forget_visitors(user_key: str) -> None:
    """Remove every visitor's own folder in *user_key*'s media folder, with
    the folders of the runs that served them and what those derived: the
    server does when it starts (``visitor_copies.drop_all``). Their
    thumbnails go with the sweep (:func:`forget_gone_runs_thumbnails`)."""
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
