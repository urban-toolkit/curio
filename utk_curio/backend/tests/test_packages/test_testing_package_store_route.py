"""``/api/testing/package-store``: the plant the #194 e2e stands an upgrade on.

``test_package_refresh_e2e.py`` installs ``curio.example-ui@1`` from the Node
Catalog, asks this route to make the store copy stale, and checks that reopening
the dataflow brings the catalog's copy back. Once in five it failed at the plant
itself, "planting staleness did not change the hash" (repeat run 37673654766):
the page was still sending requests after the install, every one of them runs a
seeding pass, and a pass that lands between the plant's record and its read-back
finds a catalog copy nobody changed whose content the catalog no longer has, so
it swaps the catalog's copy in and the plant reads back the catalog's hash.

Every other reader and writer of a user's package store holds the lock the
seeder swaps under (memo dev/99, ``test_seed.py``'s
``test_store_writers_wait_for_the_store_lock``), so a seeding pass lands before
or after it, never inside it. These tests hold the route to the same rule.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from utk_curio.backend.app.common.file_locks import keyed_thread_lock
from utk_curio.backend.app.packages.application.seeding import seed_dev_packages
from utk_curio.backend.app.packages.application.store_install import (
    install_package_from_directory,
)
from utk_curio.backend.app.packages.infrastructure.locks import (
    SEED_LOCK_FILENAME,
    SEED_LOCK_NAMESPACE,
    package_seed_lock,
)
from utk_curio.backend.app.packages.repositories import catalog_dir, seed_state
from utk_curio.backend.app.packages.repositories.store import user_packages_dir
from utk_curio.backend.app.projects.services import _user_dir_key

#: The package and file the e2e plants in: the file the #194 fix changed.
PKG_DIR = "curio.example-ui@1"
PKG_FILE = "scripts/behaviors.js"


def _post(client, **body):
    return client.post(
        "/api/testing/package-store",
        data=json.dumps(body),
        content_type="application/json",
    )


@pytest.fixture()
def installed(user_and_token):
    """``curio.example-ui@1`` installed from the catalog, as the drawer leaves it.

    Answers ``(username, store key)``.
    """
    user, _token = user_and_token
    user_key = _user_dir_key(user)
    install_package_from_directory(user_key, catalog_dir.catalog_root() / PKG_DIR)
    return user.username, user_key


def _store_snapshot(user_key: str) -> list[tuple[str, int, int]]:
    base = user_packages_dir(user_key)
    return sorted(
        (str(p.relative_to(base)), p.stat().st_mtime_ns, p.stat().st_size)
        for p in base.rglob("*") if p.is_file() and p.name != SEED_LOCK_FILENAME
    )


def test_a_seeding_pass_that_lands_mid_plant_cannot_undo_the_plant(
    client, installed, monkeypatch,
):
    """The e2e's failure, with the seeding pass put exactly where it landed.

    The pass arrives right after the plant records the stale copy as the one
    the catalog installed. If nothing stops it, it runs there. If the store
    lock keeps it waiting, it runs once the plant has answered, and it must
    still bring the catalog's copy back: the plant stands for an upgrade, so
    the refresh has to act on it.
    """
    username, user_key = installed
    store_lock = keyed_thread_lock(SEED_LOCK_NAMESPACE, user_key)
    real_mark_installed = seed_state.mark_installed
    landed: list[str] = []
    waiting: list[str] = []

    def _recorded_then_a_pass_arrives(*args, **kwargs):
        real_mark_installed(*args, **kwargs)
        if landed or waiting:
            return
        if store_lock.locked():
            waiting.append(user_key)
        else:
            landed.append(user_key)
            seed_dev_packages(user_key=user_key)

    fresh = _post(
        client, username=username, dirName=PKG_DIR, path=PKG_FILE, action="hash",
    ).get_json()
    assert fresh["catalog_sha256"], "the catalog has no copy of the probe file"
    assert fresh["sha256"] == fresh["catalog_sha256"], "the install did not copy faithfully"

    monkeypatch.setattr(seed_state, "mark_installed", _recorded_then_a_pass_arrives)
    resp = _post(client, username=username, dirName=PKG_DIR, path=PKG_FILE, action="stale")
    monkeypatch.setattr(seed_state, "mark_installed", real_mark_installed)

    assert resp.status_code == 200, resp.get_json()
    assert landed or waiting, "the plant never recorded the stale copy"
    stale = resp.get_json()
    assert stale["sha256"] != stale["catalog_sha256"], (
        "planting staleness did not change the hash, so the rest of this test "
        "would pass without proving anything"
    )

    for key in waiting:
        seed_dev_packages(user_key=key)
    after = _post(
        client, username=username, dirName=PKG_DIR, path=PKG_FILE, action="hash",
    ).get_json()
    assert after["sha256"] == after["catalog_sha256"], (
        "the seeding pass did not refresh the planted copy, so the plant no "
        "longer stands for an upgrade"
    )


@pytest.mark.parametrize("action", ["hash", "stale", "reset"])
def test_the_route_waits_for_the_store_lock(client, installed, action):
    """Each action reads or changes the store only under the store lock.

    A plant outside it lets a seeding pass refresh the copy mid-plant (the test
    above), and a read outside it can fall between a swap's two renames, when
    the package directory is briefly absent.
    """
    username, user_key = installed
    held = threading.Event()
    released = threading.Event()
    seen: dict[str, list[tuple[str, int, int]]] = {}

    def _hold_the_store_lock():
        try:
            with package_seed_lock(user_key):
                seen["before"] = _store_snapshot(user_key)
                held.set()
                time.sleep(2.0)
                seen["during"] = _store_snapshot(user_key)
                released.set()
        finally:
            held.set()

    holder = threading.Thread(target=_hold_the_store_lock)
    holder.start()
    try:
        assert held.wait(30), "the store lock was never taken"
        resp = _post(client, username=username, dirName=PKG_DIR, path=PKG_FILE, action=action)
        answered_while_held = not released.is_set()
    finally:
        holder.join(60)

    assert not holder.is_alive(), "the lock holder never finished"
    assert resp.status_code == 200, resp.get_json()
    assert not answered_while_held, f"{action} answered while the store lock was held"
    assert seen["during"] == seen["before"], (
        f"{action} changed the store while the store lock was held"
    )
