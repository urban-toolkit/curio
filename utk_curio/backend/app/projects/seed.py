"""Seed example projects from docs/examples/ into the guest user's projects."""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects import repositories as repo
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.models import Project
from utk_curio.backend.app.projects.schemas import VALID_ACCENTS, _slugify
from utk_curio.backend.app.projects.services import _is_shared_guest, _user_dir_key
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


def _example_files(examples_dir: Path) -> list[Path]:
    return sorted(p for p in examples_dir.glob("*.json") if p.is_file())


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


def _example_id(stem: str, user=None) -> str:
    """The deterministic project id for one example, scoped to ``user``.

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
        return str(uuid.uuid5(_EXAMPLES_NAMESPACE, stem))
    return str(uuid.uuid5(_EXAMPLES_NAMESPACE, f"{user.id}:{stem}"))


def seed_example_projects(user, *, prune: bool | None = None) -> int:
    """Seed/refresh example projects for ``user`` from docs/examples/.

    Each example JSON gets a deterministic project_id derived from its
    filename, so re-running on the same set replaces the existing rows
    (overwrite semantics) without ever colliding with user-created
    projects (which use random uuid4s).
    """
    # Registered accounts get their own copies (#200). Under ``--auth`` the
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

    examples_dir = _repo_root() / "docs" / "examples"
    if not examples_dir.exists():
        logger.warning("No examples directory at %s", examples_dir)
        return 0

    ukey = _user_dir_key(user)
    seeded = 0
    keep_ids = {_example_id(p.stem, user) for p in _example_files(examples_dir)}

    for i, json_path in enumerate(_example_files(examples_dir)):
        try:
            spec = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read example %s", json_path)
            continue

        stem = json_path.stem
        project_id = _example_id(stem, user)
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
                if existing is not None and existing.user_id == user.id:
                    existing.name = name
                    existing.description = description
                    existing.thumbnail_accent = accent
                    existing.folder_path = folder
                    existing.archived_at = None
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


def ensure_user_examples_seeded(user) -> int:
    """Give ``user`` their copy of the examples, once, on first listing.

    Seeding happens at sign-up, but that only covers accounts created after
    this shipped. Everyone who registered before it - and the shared guest on
    a stack started without ``--with-examples`` - would still see an empty
    gallery, so the listing back-fills the same way packages and datasets
    already self-heal per user.

    The marker is what keeps it a back-fill rather than a reset: an example the
    user deliberately deleted must stay deleted, and without a marker every
    listing would resurrect it. Pruning is never enabled here.
    """
    # Read at call time, not import time, so the launcher's value is honoured
    # and a test can flip it. Default off, matching ``config.CURIO_SEED_EXAMPLES``:
    # a stack started without ``--with-examples`` seeds nobody, exactly as before.
    if not _env_flag("CURIO_SEED_EXAMPLES"):
        return 0
    ukey = _user_dir_key(user)
    marker = _seeded_marker(ukey)
    if marker.exists():
        return 0
    try:
        seeded = seed_example_projects(user, prune=False)
    except Exception:
        logger.exception("Back-filling examples failed for user %s", user.id)
        return 0
    # Written even for a zero-seed: a missing examples directory is not a
    # reason to retry the whole walk on every listing.
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(seeded), encoding="utf-8")
    except OSError:
        logger.exception("Could not write the examples marker at %s", marker)
    return seeded


def _prune_non_example_projects(user, ukey: str, keep_ids: set[str]) -> int:
    """Delete every guest project that isn't part of the seeded set.

    Mirrors the overwrite posture: ``--with-examples`` / ``--deploy`` always
    lands on exactly the curated examples, with leftover scratch projects
    (e.g. "DefaultDataflow", auto-generated test fixtures) cleaned up.
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
