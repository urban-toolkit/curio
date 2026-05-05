"""Seed example projects from docs/examples/ into the guest user's projects."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects import repositories as repo
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.models import Project
from utk_curio.backend.app.projects.schemas import VALID_ACCENTS, _slugify
from utk_curio.backend.app.projects.services import _is_shared_guest, _user_dir_key

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


def _description_from_spec(spec: dict) -> Optional[str]:
    if not isinstance(spec, dict):
        return None
    dataflow = spec.get("dataflow")
    desc = dataflow.get("description") if isinstance(dataflow, dict) else None
    if isinstance(desc, str):
        cleaned = desc.strip()
        return cleaned or None
    return None


def _example_id(stem: str) -> str:
    return str(uuid.uuid5(_EXAMPLES_NAMESPACE, stem))


def _copy_example_data(launch_cwd: Path, examples_data_dir: Path) -> None:
    if not examples_data_dir.exists():
        return
    dest_root = launch_cwd / "data"
    dest_root.mkdir(parents=True, exist_ok=True)
    for entry in examples_data_dir.iterdir():
        dest = dest_root / entry.name
        try:
            if entry.is_dir():
                shutil.copytree(entry, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, dest)
        except Exception:
            logger.exception("Failed to copy example data %s", entry)


def seed_example_projects(user) -> int:
    """Seed/refresh example projects for ``user`` from docs/examples/.

    Each example JSON gets a deterministic project_id derived from its
    filename, so re-running on the same set replaces the existing rows
    (overwrite semantics) without ever colliding with user-created
    projects (which use random uuid4s).
    """
    if not _is_shared_guest(user):
        logger.warning(
            "seed_example_projects refused: user %r is not the shared guest",
            getattr(user, "username", None),
        )
        return 0

    examples_dir = _repo_root() / "docs" / "examples"
    if not examples_dir.exists():
        logger.warning("No examples directory at %s", examples_dir)
        return 0

    ukey = _user_dir_key(user)
    seeded = 0
    keep_ids = {_example_id(p.stem) for p in _example_files(examples_dir)}

    for i, json_path in enumerate(_example_files(examples_dir)):
        try:
            spec = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read example %s", json_path)
            continue

        stem = json_path.stem
        project_id = _example_id(stem)
        name = _name_from_stem(stem)
        description = _description_from_spec(spec)
        accent = _ACCENT_CYCLE[i % len(_ACCENT_CYCLE)]

        # Stamp the canonical workflow name into the spec so the canvas shows
        # the project name on load (the example JSONs don't carry a name field
        # of their own, and TrillGenerator falls back to "DefaultWorkflow").
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

    pruned = _prune_non_example_projects(user, ukey, keep_ids)
    if pruned:
        logger.info("Pruned %d non-example guest project(s)", pruned)

    launch_cwd = Path(os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd())
    _copy_example_data(launch_cwd, examples_dir / "data")

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
