"""Seed the dataflows Curio ships (see ``shipped.py``) into each account's projects."""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Iterable, Optional

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects import repositories as repo
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.models import Project
from utk_curio.backend.app.projects.schemas import VALID_ACCENTS, _slugify
from utk_curio.backend.app.projects.services import _is_shared_guest, _user_dir_key
from utk_curio.backend.app.projects.shipped import (  # noqa: F401 - re-exported
    SOURCE_EXAMPLE,
    SOURCE_TEST,
    SOURCE_USE_CASE,
    USE_CASES,
    ShippedDataflow,
    examples_dir,
    shipped_dataflows,
)
from utk_curio.backend.config import _env_flag

logger = logging.getLogger(__name__)

# Stable namespace so the same example filename always maps to the same
# project_id across restarts. Re-seeding then upserts the same row instead
# of creating duplicates, and a user-created project (random uuid4) cannot
# collide with one of these by accident.
_EXAMPLES_NAMESPACE = uuid.UUID("a3f1c0d4-1111-4b8e-9a6e-c0ff33ee5eed")

_ACCENT_CYCLE = sorted(VALID_ACCENTS)


def _repo_root() -> Path:
    # this file: utk_curio/backend/app/projects/seed.py -> repo root is 4 parents up
    return Path(__file__).resolve().parents[4]




def _name_from_stem(stem: str) -> str:
    no_prefix = re.sub(r"^\d+[-_]?", "", stem)
    cleaned = no_prefix.replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else stem


def _name_from_spec(spec: dict) -> Optional[str]:
    """The example's own ``dataflow.name``, if it has one.

    Every curated example carries this field, and it is the title the docs table
    and the walkthroughs use. Deriving the name from the filename instead turned
    ``Vega-Lite chained transforms`` into ``Vega lite chained transforms`` and
    ``Street-level computer vision`` into ``Street vision cv analysis`` (#148),
    so the spec wins and the filename is only a fallback.
    """
    if not isinstance(spec, dict):
        return None
    dataflow = spec.get("dataflow")
    name = dataflow.get("name") if isinstance(dataflow, dict) else None
    if isinstance(name, str):
        cleaned = name.strip()
        return cleaned or None
    return None


def _description_from_spec(spec: dict) -> Optional[str]:
    if not isinstance(spec, dict):
        return None
    dataflow = spec.get("dataflow")
    desc = dataflow.get("description") if isinstance(dataflow, dict) else None
    if isinstance(desc, str):
        cleaned = desc.strip()
        return cleaned or None
    return None


def _example_id(key: str, user=None) -> str:
    """The deterministic project id for one shipped dataflow, scoped to ``user``.

    ``Project.id`` is a **global** primary key, so a namespace keyed on the
    filename alone gives every user the same ids. Seeding a second account then
    takes the insert branch with an id that already exists, raises an
    IntegrityError, and the caller's broad ``except`` swallows it into a silent
    zero-seed (#200).

    The shared guest keeps the bare-stem id so installs seeded before this
    change still upsert their existing rows rather than growing a duplicate set
    beside them.
    """
    if user is None or _is_shared_guest(user):
        return str(uuid.uuid5(_EXAMPLES_NAMESPACE, key))
    return str(uuid.uuid5(_EXAMPLES_NAMESPACE, f"{user.id}:{key}"))


def shipped_sources(user) -> dict[str, str]:
    """``project id -> source`` for every dataflow Curio seeds for ``user``.

    Derived, not stored: ``Project`` has no "this one shipped with Curio"
    column, and it does not need one - a shipped dataflow's id is ``uuid5`` of
    its key (scoped to the account since #200), so the map can be recomputed
    from ``docs/examples/`` whenever it is asked for. That is also what makes a
    duplicate or an imported copy the user's own: it has a fresh id.
    """
    return {_example_id(s.key, user): s.source for s in shipped_dataflows()}


def example_project_ids(user) -> set[str]:
    """The project ids this user's shipped dataflows occupy.

    Callers use it to keep a shipped dataflow out of reach of Delete. That rule
    matches the one the Data Catalog has had since "hide delete for anything
    that came from the shared catalog": you may edit and rename what Curio
    seeded for you, but removing it is not yours to do.
    """
    return set(shipped_sources(user))


def is_example_project(user, project_id: str) -> bool:
    """Is ``project_id`` one of the dataflows Curio seeded for ``user``?"""
    return project_id in example_project_ids(user)


def seed_example_projects(
    user,
    *,
    prune: bool | None = None,
    overwrite: bool | None = None,
    only_keys: Optional[Iterable[str]] = None,
) -> int:
    """Seed/refresh the shipped dataflows for ``user``.

    Each file gets a deterministic project_id derived from its key, so
    re-running on the same set replaces the existing rows (overwrite semantics)
    without ever colliding with user-created projects (which use random
    uuid4s). *only_keys* limits the walk to those keys; prune still keeps the
    whole shipped set.
    """
    # Registered accounts get their own copies (#200). Under ``--deploy`` the
    # signed-in user is not the guest that owned the seeded rows, so the
    # gallery came up empty for everyone with an account; ``--deploy`` carried
    # the identical defect. The dataset half of this was already fixed in
    # services.py and the project half never was.
    is_guest = _is_shared_guest(user)

    # Pruning is destructive - it deletes every project of the seeded user that
    # is not an example, storage tree included. That is the right posture for
    # the shared guest, whose projects are disposable scratch, and catastrophic
    # for a registered account. Default to the guest's behaviour exactly.
    if prune is None:
        prune = is_guest

    # Overwriting is the guest's posture too: its examples are reset to the
    # shipped copy on every boot. For a registered account an example is theirs
    # once seeded - renamed, edited, saved - and a back-fill that rewrote the
    # row and the spec from docs/examples/ silently undid that work the next
    # time the projects list was opened (#270). Default to the guest's behaviour
    # exactly, as ``prune`` does; ``ensure_user_examples_seeded`` passes False.
    if overwrite is None:
        overwrite = is_guest

    shipped = shipped_dataflows()
    if not shipped:
        logger.warning("No shipped dataflows under %s", examples_dir())
        return 0

    ukey = _user_dir_key(user)
    seeded = 0
    keep_ids = {_example_id(s.key, user) for s in shipped}
    wanted = set(only_keys) if only_keys is not None else None

    # Tests first: "Recent activity" puts the newest row on top, so what is
    # seeded last leads a fresh gallery, and that should be the examples. The
    # accent stays keyed to the file's place in the list.
    in_seed_order = sorted(enumerate(shipped), key=lambda pair: pair[1].source != SOURCE_TEST)
    for i, entry in in_seed_order:
        if wanted is not None and entry.key not in wanted:
            continue
        json_path = entry.path
        try:
            spec = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read example %s", json_path)
            continue

        stem = json_path.stem
        project_id = _example_id(entry.key, user)
        name = _name_from_spec(spec) or _name_from_stem(stem)
        description = _description_from_spec(spec)
        accent = _ACCENT_CYCLE[i % len(_ACCENT_CYCLE)]

        # Keep the canvas title in sync with the project name so TrillGenerator
        # never falls back to "DefaultWorkflow". `name` is now the spec's own
        # `dataflow.name` whenever it has one, so this is a no-op for every
        # curated example and only fills in a name for a spec that lacks one.
        if isinstance(spec.get("dataflow"), dict):
            spec["dataflow"]["name"] = name

        try:
            with db.session.begin_nested():
                folder = str(storage.project_dir(ukey, project_id))
                existing = db.session.get(Project, project_id)
                if existing is not None and existing.user_id == user.id and not overwrite:
                    # Theirs now. Repair a missing spec file (the row without
                    # its spec is unopenable) and otherwise leave it alone.
                    if storage.read_spec(ukey, project_id) is None:
                        storage.write_spec(ukey, project_id, spec)
                    continue
                if existing is not None and existing.user_id == user.id:
                    existing.name = name
                    existing.description = description
                    existing.thumbnail_accent = accent
                    existing.folder_path = folder
                    existing.spec_revision = (existing.spec_revision or 0) + 1
                    existing.slug = repo._unique_slug(
                        user.id, _slugify(name), exclude_id=project_id
                    )
                    project = existing
                else:
                    project = Project(
                        id=project_id,
                        user_id=user.id,
                        name=name,
                        slug=repo._unique_slug(user.id, _slugify(name)),
                        description=description,
                        folder_path=folder,
                        thumbnail_accent=accent,
                    )
                    db.session.add(project)
                    db.session.flush()

                storage.write_spec(ukey, project_id, spec)
                storage.write_manifest(
                    ukey,
                    project_id,
                    project.spec_revision,
                    [],
                    name=name,
                    description=description,
                    thumbnail_accent=accent,
                )
                seeded += 1
        except Exception:
            logger.exception("Failed to seed example %s", stem)

    if seeded:
        db.session.commit()

    if prune:
        pruned = _prune_non_example_projects(user, ukey, keep_ids)
        if pruned:
            logger.info("Pruned %d non-example guest project(s)", pruned)

    return seeded


def _seeded_marker(ukey: str) -> Path:
    return storage.user_dir(ukey) / "examples.seeded"


def _read_marker(marker: Path) -> tuple[str | None, set[str] | None]:
    """``(owner, keys)`` from the marker.

    *owner* is ``None`` for "no marker" and for "a marker from before this
    recorded an owner", and both mean the same thing to the caller: it cannot
    be trusted to describe whoever holds this id now. *keys* is ``None`` for a
    marker written before it listed what it seeded.
    """
    owner: str | None = None
    keys: set[str] | None = None
    try:
        for line in marker.read_text(encoding="utf-8").splitlines():
            if line.startswith("user="):
                owner = line[len("user="):].strip() or None
            elif line.startswith("keys="):
                keys = {k for k in line[len("keys="):].strip().split(",") if k}
    except OSError:
        return None, None
    return owner, keys


def ensure_user_examples_seeded(user) -> int:
    """Give ``user`` each shipped dataflow once, on the listing after it ships.

    Seeding happens at sign-up, but that only covers accounts created after
    this shipped. Everyone who registered before it - and the shared guest on
    a stack started without ``--with-examples`` - would still see an empty
    gallery, so the listing back-fills the same way packages and datasets
    already self-heal per user.

    The marker is what keeps it a back-fill rather than a reset: it lists the
    keys already seeded, so a dataflow the user changed or removed is not put
    back, while one that shipped after the account was seeded still arrives.
    A marker from before it listed keys counts the rows that exist as seeded.
    Pruning is never enabled here.

    **The marker names the account, not the id slot.** It lives on disk under
    ``.curio/users/<id>/`` while the id it is keyed to lives in the database,
    and those two can come apart: truncate or restore the database against an
    existing ``.curio`` directory and sqlite hands the next signup a rowid that
    has been used before. A marker that said only "seeded" then belonged to
    whoever came first, and the new occupant of that id silently got an empty
    gallery - which is exactly what the e2e harness produces, since it
    truncates ``user`` between tests. Recording the username and requiring it
    to match costs one line and makes the marker mean what it says.
    """
    # Read at call time, not import time, so the launcher's value is honoured
    # and a test can flip it. Default off, matching ``config.CURIO_SEED_EXAMPLES``:
    # a stack started without ``--with-examples`` seeds nobody, exactly as before.
    if not _env_flag("CURIO_SEED_EXAMPLES"):
        return 0
    ukey = _user_dir_key(user)
    marker = _seeded_marker(ukey)
    owner = str(getattr(user, "username", "") or "")
    shipped_keys = [s.key for s in shipped_dataflows()]

    recorded: set[str] = set()
    if marker.exists():
        marker_owner, marker_keys = _read_marker(marker)
        if marker_owner == owner:
            if marker_keys is None:
                ids = {
                    row.id for row in
                    Project.query.filter(Project.user_id == user.id).all()
                }
                marker_keys = {k for k in shipped_keys if _example_id(k, user) in ids}
            recorded = marker_keys
    missing = [k for k in shipped_keys if k not in recorded]
    if not missing:
        return 0
    try:
        seeded = seed_example_projects(
            user, prune=False, overwrite=False, only_keys=missing,
        )
    except Exception:
        logger.exception("Back-filling examples failed for user %s", user.id)
        return 0
    # Written even for a zero-seed: a missing examples directory is not a
    # reason to retry the whole walk on every listing.
    keys = ",".join(sorted(recorded | set(missing)))
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"user={owner}\nkeys={keys}\ncount={seeded}\n", encoding="utf-8",
        )
    except OSError:
        logger.exception("Could not write the examples marker at %s", marker)
    return seeded


def _prune_non_example_projects(user, ukey: str, keep_ids: set[str]) -> int:
    """Delete every guest project that isn't part of the seeded set.

    Mirrors the overwrite posture: ``--with-examples`` always
    lands on exactly the shipped dataflows, with leftover scratch projects
    (e.g. "DefaultDataflow") cleaned up.
    """
    pruned = 0
    stale = (
        Project.query
        .filter(Project.user_id == user.id, Project.id.notin_(keep_ids))
        .all()
    )
    for project in stale:
        try:
            with db.session.begin_nested():
                storage.delete_tree(ukey, project.id)
                db.session.delete(project)
                pruned += 1
        except Exception:
            logger.exception("Failed to prune non-example project %s", project.id)
    if pruned:
        db.session.commit()
    return pruned
