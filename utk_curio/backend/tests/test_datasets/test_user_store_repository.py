"""Account-level user-store dataset listing.

The user store surfaces *imported* and *computed* datasets as standalone
catalog items so they stay visible with no project ref. Computed node outputs
are account-level assets by default (saved on generation, not auto-installed),
so they list here alongside imports.
"""

from __future__ import annotations

import types


def _stub_user(user_id: int = 1):
    # Enough surface for ``_user_dir_key`` / ``_is_shared_guest``: a real,
    # non-guest user resolves to ``str(user.id)``.
    return types.SimpleNamespace(id=user_id, is_guest=False, username="alice")


def test_user_store_lists_imported_and_computed(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file_for_node,
        install_imported_file,
    )
    from utk_curio.backend.app.datasets.repositories.user_store import (
        UserDatasetRepository,
    )

    user = _stub_user()
    user_key = "1"

    install_imported_file(user_key, b"a,b\n1,2\n", "cities.csv", "csv")
    # A computed node-output copy is now an account-level asset and IS listed.
    install_computed_file_for_node(
        user_key, b'{"x": 1}', "out.json", "json",
        node_id="n-123", dataflow_id="flow-1",
    )

    items = UserDatasetRepository(user).list_items()

    by_origin = {item["id"]: item["origin"] for item in items}
    assert any(i.startswith("imported.") and o == "imported" for i, o in by_origin.items())
    computed = [i for i, o in by_origin.items() if o == "computed"]
    assert computed == ["computed.flow-1.n-123"], by_origin
    # Account-level rows are never pre-marked installed.
    for item in items:
        assert item["installed"] is False


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
