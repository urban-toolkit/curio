"""Account-level user-store dataset listing (register-only imports).

The user store surfaces *imported* datasets as standalone catalog items so a
register-only import stays visible with no project ref. Computed node-output
copies keep their existing per-project path and must NOT be listed here.
"""

from __future__ import annotations

import types


def _stub_user(user_id: int = 1):
    # Enough surface for ``_user_dir_key`` / ``_is_shared_guest``: a real,
    # non-guest user resolves to ``str(user.id)``.
    return types.SimpleNamespace(id=user_id, is_guest=False, username="alice")


def test_user_store_lists_imported_excludes_computed(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file,
        install_imported_file,
    )
    from utk_curio.backend.app.datasets.repositories.user_store import (
        UserDatasetRepository,
    )

    user = _stub_user()
    user_key = "1"

    install_imported_file(user_key, b"a,b\n1,2\n", "cities.csv", "csv")
    # A computed node-output copy living in the same store must be excluded.
    install_computed_file(
        user_key, b'{"x": 1}', "out.json", "json", node_id="n-123"
    )

    items = UserDatasetRepository(user).list_items()

    origins = {item["id"] for item in items}
    assert any(i.startswith("imported.") for i in origins)
    assert not any(i.startswith("computed.") for i in origins), origins
    for item in items:
        assert item["installed"] is False
        assert item["origin"] == "imported"


def test_user_store_empty_without_user():
    from utk_curio.backend.app.datasets.repositories.user_store import (
        UserDatasetRepository,
    )

    assert UserDatasetRepository(None).list_items() == []


def test_user_store_skips_malformed_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir
    from utk_curio.backend.app.datasets.install.installer import install_imported_file
    from utk_curio.backend.app.datasets.repositories.user_store import (
        UserDatasetRepository,
    )

    user_key = "1"
    install_imported_file(user_key, b"a\n1\n", "ok.csv", "csv")
    # A dir that matches the imported prefix + dir regex but has no manifest.
    broken = user_datasets_dir(user_key) / "imported.xdeadbeef@1"
    broken.mkdir(parents=True, exist_ok=True)

    items = UserDatasetRepository(_stub_user()).list_items()

    # The good import is listed; the broken dir is skipped, not fatal.
    assert len(items) == 1
    assert items[0]["id"].startswith("imported.")
