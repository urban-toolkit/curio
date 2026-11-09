"""Two processes never migrate one account's dataset ids at once.

The migration of an account's computed dataset ids (``migrations.py``) stages
each folder's new manifest, renames the folder, swaps the manifest in and
rewrites the dataflows' refs. It ran behind a thread lock and the process's
own set of migrated accounts until a run marked the account done on disk, so
two backend processes listing one account's datasets at once could each run
it over the same folders: one could discard the manifest the other had just
staged (it reads as a crash before the rename) and leave a renamed folder
whose manifest still names its old id.

The test forks a listing whose migration stops partway, then lists from this
process (``_support/two_processes.py``).
"""
from __future__ import annotations

import os

ACCOUNT = "7"


def test_two_processes_never_migrate_one_account_at_once(tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets.application import migrations
    from utk_curio.backend.tests._support.two_processes import Window, race

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    window = Window()
    migrating = tmp_path / "migrating"
    migrating.mkdir()
    met: list[list[str]] = []

    def _migrate(user_key):
        others = sorted(entry.name for entry in migrating.iterdir())
        if others:
            met.append(others)
        mine = migrating / str(os.getpid())
        mine.touch()
        try:
            window.stop_here()
        finally:
            mine.unlink()
        return 0

    monkeypatch.setattr(migrations, "migrate_computed_dataset_ids", _migrate)

    raced = race(
        window,
        lambda: migrations.ensure_computed_ids_migrated(ACCOUNT),
        lambda: migrations.ensure_computed_ids_migrated(ACCOUNT),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    assert not met, f"this process migrated the account while process {met[0]} was migrating it"
    assert migrations._marker_path(ACCOUNT).is_file(), "no run marked the account migrated"
