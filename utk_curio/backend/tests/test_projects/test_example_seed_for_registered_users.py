"""Example dataflows reach registered accounts, not just the shared guest (#200).

Examples were seeded to exactly one user - the shared guest - and project
listing is a plain owner filter, so under ``--auth`` (and ``--deploy``, which
carries the identical defect) every account signed in to an empty gallery. The
repo had already fixed the *dataset* half of this and never the project half.

Two landmines make the naive fix worse than the bug, and each has a test here:

1. ``Project.id`` is a **global** primary key while ``_example_id`` derived it
   from the filename alone, so a second user's seed collides on insert. The
   IntegrityError was swallowed by a broad ``except`` into a silent zero-seed.
2. ``_prune_non_example_projects`` deletes every project of the seeded user
   that is not an example, storage tree included. Running that for a registered
   account destroys their work.
"""
from __future__ import annotations

import uuid

import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate
from utk_curio.backend.app.projects.repositories import list_for_user
from utk_curio.backend.app.projects.seed import (
    _seeded_marker,
    _EXAMPLES_NAMESPACE,
    _example_files,
    _example_id,
    _repo_root,
    ensure_user_examples_seeded,
    seed_example_projects,
)
from utk_curio.backend.app.users.models import User, UserSession


def _example_stems() -> list[str]:
    return [p.stem for p in _example_files(_repo_root() / "docs" / "examples")]


def _make_user(db, username: str, token: str) -> tuple[User, str]:
    u = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSession(user_id=u.id, token=token))
    db.session.commit()
    return u, token


@pytest.fixture(autouse=True)
def examples_enabled(monkeypatch):
    """The back-fill is gated on the launcher's ``--with-examples`` flag.

    Off by default, matching ``config.CURIO_SEED_EXAMPLES``, so a stack started
    without the flag still seeds nobody. Every test here is about what happens
    when it IS on; ``test_seeding_is_off_without_the_flag`` covers the other side.
    """
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")


@pytest.fixture()
def shared_guest(db):
    """The real shared guest, which ``_is_shared_guest`` recognises by username."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    u = User(username=CURIO_SHARED_GUEST_USERNAME, name="Guest", is_guest=True)
    db.session.add(u)
    db.session.commit()
    return u


def test_registered_user_gets_examples(app, db, user_and_token):
    """Fails before the fix: the refusal returned 0 for anyone but the guest."""
    user, _ = user_and_token

    seeded = seed_example_projects(user)

    stems = _example_stems()
    assert stems, "no example dataflows on disk to seed"
    assert seeded == len(stems)

    rows = list_for_user(user.id)
    assert len(rows) == len(stems)
    for row in rows:
        assert storage.read_spec(str(user.id), row.id) is not None, (
            f"{row.name} has a DB row but no spec on disk"
        )


def test_two_users_each_get_their_own_copy(app, db, user_and_token):
    """Landmine 1: a global PK made the second user's seed collide silently."""
    alice, _ = user_and_token
    bob, _ = _make_user(db, "bob", "bob-token")

    assert seed_example_projects(alice) == len(_example_stems())
    assert seed_example_projects(bob) == len(_example_stems())

    alice_ids = {p.id for p in list_for_user(alice.id)}
    bob_ids = {p.id for p in list_for_user(bob.id)}

    assert len(alice_ids) == len(_example_stems())
    assert len(bob_ids) == len(_example_stems())
    assert alice_ids.isdisjoint(bob_ids), "both users share example project ids"

    # Each user's own copy is on disk under their own key.
    for pid in bob_ids:
        assert storage.read_spec(str(bob.id), pid) is not None


def test_seeding_does_not_delete_a_users_own_project(app, db, user_and_token):
    """Landmine 2: the prune would have deleted the user's work, files included."""
    user, _ = user_and_token

    mine = services.save_project(
        user,
        ProjectCreate(name="My own work", spec={"dataflow": {"name": "Mine"}}),
    )

    seed_example_projects(user)

    surviving = {p.id for p in list_for_user(user.id)}
    assert mine.id in surviving, "seeding deleted the user's own project"
    assert storage.read_spec(str(user.id), mine.id) is not None, (
        "the project row survived but its spec file was deleted"
    )


def test_guest_prune_still_runs(app, db, shared_guest):
    """The guest's overwrite posture is unchanged: scratch projects are pruned."""
    scratch = services.save_project(
        shared_guest,
        ProjectCreate(name="Scratch", spec={"dataflow": {"name": "Scratch"}}),
    )

    seed_example_projects(shared_guest)

    surviving = {p.id for p in list_for_user(shared_guest.id)}
    assert scratch.id not in surviving, (
        "the guest's non-example project survived; --with-examples must land on "
        "exactly the curated set"
    )


def test_guest_ids_are_unchanged(app, db, shared_guest):
    """Installs seeded before this change must upsert, not duplicate."""
    for stem in _example_stems():
        assert _example_id(stem, shared_guest) == str(
            uuid.uuid5(_EXAMPLES_NAMESPACE, stem)
        )
    # And a registered user's are genuinely different.
    alice, _ = _make_user(db, "alice2", "alice2-token")
    for stem in _example_stems():
        assert _example_id(stem, alice) != _example_id(stem, shared_guest)


def test_seed_is_idempotent(app, db, user_and_token):
    user, _ = user_and_token

    seed_example_projects(user)
    first = {p.id for p in list_for_user(user.id)}
    seed_example_projects(user)
    second = {p.id for p in list_for_user(user.id)}

    assert first == second, "re-seeding duplicated the examples"


def test_backfill_does_not_resurrect_a_deleted_example(app, db, user_and_token):
    """The marker is what makes the listing back-fill safe to run every time."""
    user, _ = user_and_token

    assert ensure_user_examples_seeded(user) == len(_example_stems())

    victim = list_for_user(user.id)[0]
    services.delete_project(user, victim.id)
    assert victim.id not in {p.id for p in list_for_user(user.id)}

    # A second call is a no-op, so the deliberate deletion stands.
    assert ensure_user_examples_seeded(user) == 0
    assert victim.id not in {p.id for p in list_for_user(user.id)}


def test_listing_backfills_for_a_user_seeded_before_the_fix(app, db, user_and_token):
    """`list_projects` is the self-heal path, mirroring packages and datasets."""
    user, _ = user_and_token
    assert list_for_user(user.id) == []

    summaries = services.list_projects(user)

    assert len(summaries) == len(_example_stems())


def test_a_reused_user_id_does_not_inherit_the_previous_occupant_marker(
    app, db, user_and_token, tmp_curio
):
    """The marker names the account, not the id slot.

    It lives on disk under ``.curio/users/<id>/`` while the id lives in the
    database, and the two come apart whenever the database is truncated or
    restored against an existing ``.curio`` directory - sqlite then hands the
    next signup a rowid that has been used before. Keyed on the id alone, the
    marker belonged to whoever came first and the new occupant silently got an
    empty gallery. The e2e harness reproduces this on every run, because it
    truncates ``user`` between tests.
    """
    first, _ = user_and_token
    assert ensure_user_examples_seeded(first) == len(_example_stems())
    marker = storage.user_dir(str(first.id)) / "examples.seeded"
    assert marker.exists()
    assert f"user={first.username}" in marker.read_text(encoding="utf-8")

    # The database goes away; the files do not. A different account then takes
    # the same id, exactly as it does after a truncation. Rows go in the order
    # the e2e harness truncates them (projects before users), or the FK from
    # project.user_id refuses.
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.models import UserSession

    reused_id = first.id
    Project.query.filter_by(user_id=reused_id).delete(synchronize_session=False)
    UserSession.query.filter_by(user_id=reused_id).delete(synchronize_session=False)
    db.session.delete(first)
    db.session.commit()

    successor = User(username="successor", name="Successor", email="s@test.com")
    successor.id = reused_id
    db.session.add(successor)
    db.session.commit()
    assert successor.id == reused_id
    assert list_for_user(successor.id) == []

    # THE POINT: the successor gets their own examples, not an empty gallery.
    assert ensure_user_examples_seeded(successor) == len(_example_stems())
    assert len(list_for_user(successor.id)) == len(_example_stems())
    assert f"user={successor.username}" in marker.read_text(encoding="utf-8")


def test_the_same_account_is_still_seeded_only_once(app, db, user_and_token):
    """The marker must still stop a deliberate deletion being undone."""
    user, _ = user_and_token
    assert ensure_user_examples_seeded(user) == len(_example_stems())

    victim = list_for_user(user.id)[0]
    services.delete_project(user, victim.id)

    assert ensure_user_examples_seeded(user) == 0
    assert victim.id not in {p.id for p in list_for_user(user.id)}


def test_a_legacy_marker_without_an_owner_is_not_trusted(app, db, user_and_token):
    """Markers written before this recorded an owner say nothing about who.

    Treating them as valid would preserve the bug for exactly the installs that
    already have one. They are re-seeded once and rewritten in the named form;
    the cost is that a user who had deleted an example gets it back on that one
    occasion, which is self-correcting from then on.
    """
    user, _ = user_and_token
    marker = storage.user_dir(str(user.id)) / "examples.seeded"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("11", encoding="utf-8")  # the old format: a bare count

    assert ensure_user_examples_seeded(user) == len(_example_stems())
    assert f"user={user.username}" in marker.read_text(encoding="utf-8")
    # ...and now it is trusted, so it does not re-seed a second time.
    assert ensure_user_examples_seeded(user) == 0


@pytest.mark.parametrize("flag", ["0", None])
def test_seeding_is_off_without_the_flag(app, db, user_and_token, monkeypatch, flag):
    """`--with-examples` is what turns this on; unset means off, as before."""
    user, _ = user_and_token
    if flag is None:
        monkeypatch.delenv("CURIO_SEED_EXAMPLES", raising=False)
    else:
        monkeypatch.setenv("CURIO_SEED_EXAMPLES", flag)

    assert ensure_user_examples_seeded(user) == 0
    assert list_for_user(user.id) == []
    assert services.list_projects(user) == []


# ---------------------------------------------------------------------------
# The back-fill must not rewrite what the user has changed (#270)
# ---------------------------------------------------------------------------

def _drop_marker(user):
    from utk_curio.backend.app.projects.services import _user_dir_key
    marker = _seeded_marker(_user_dir_key(user))
    if marker.exists():
        marker.unlink()


def test_backfill_keeps_a_renamed_example(app, db, user_and_token):
    """A renamed example reverted to its shipped name on the next listing.

    ``seed_example_projects`` rewrote name/description/spec for every existing
    example whenever it ran, and ``ensure_user_examples_seeded`` re-runs it
    whenever the marker is missing - a truncated DB, a legacy marker, a failed
    write. The Projects list calls it on every visit. So visiting the list could
    hand back the old name of a dataflow the user had just renamed and saved.
    """
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, _ = user_and_token
    ensure_user_examples_seeded(user)
    victim = list_for_user(user.id)[0]

    services.rename_project(user, victim.id, "My renamed copy")
    _drop_marker(user)

    assert ensure_user_examples_seeded(user) == 0
    renamed = next(p for p in list_for_user(user.id) if p.id == victim.id)
    assert renamed.name == "My renamed copy"
    # And the spec file was left alone too (it was not rewritten from disk).
    assert storage.read_spec(_user_dir_key(user), victim.id) is not None


def test_backfill_keeps_an_edited_example_spec(app, db, user_and_token):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, _ = user_and_token
    ensure_user_examples_seeded(user)
    victim = list_for_user(user.id)[0]
    ukey = _user_dir_key(user)

    spec = storage.read_spec(ukey, victim.id)
    spec["dataflow"]["nodes"].append({
        "id": "user-added", "type": "curio.builtin/data-loading",
        "x": 0, "y": 0, "content": "return 1",
    })
    storage.write_spec(ukey, victim.id, spec)
    _drop_marker(user)

    ensure_user_examples_seeded(user)
    after = storage.read_spec(ukey, victim.id)
    assert any(n["id"] == "user-added" for n in after["dataflow"]["nodes"])


def test_backfill_still_creates_an_example_that_is_missing(app, db, user_and_token):
    user, _ = user_and_token
    ensure_user_examples_seeded(user)
    victim = list_for_user(user.id)[0]
    services.delete_project(user, victim.id)
    assert victim.id not in {p.id for p in list_for_user(user.id)}
    _drop_marker(user)

    assert ensure_user_examples_seeded(user) == 1
    assert victim.id in {p.id for p in list_for_user(user.id)}


def test_backfill_repairs_an_example_whose_spec_file_is_gone(app, db, user_and_token):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, _ = user_and_token
    ensure_user_examples_seeded(user)
    victim = list_for_user(user.id)[0]
    ukey = _user_dir_key(user)
    services.rename_project(user, victim.id, "Still mine")
    # write_spec returns the file it wrote; that is the one to remove.
    storage.write_spec(ukey, victim.id, storage.read_spec(ukey, victim.id)).unlink()
    _drop_marker(user)

    ensure_user_examples_seeded(user)
    assert storage.read_spec(ukey, victim.id) is not None
    assert next(p for p in list_for_user(user.id) if p.id == victim.id).name == "Still mine"


def test_guest_boot_still_resets_its_examples(app, db, shared_guest):
    """The guest's posture is unchanged: its examples are scratch, reset on boot."""
    seed_example_projects(shared_guest)
    victim = list_for_user(shared_guest.id)[0]
    services.rename_project(shared_guest, victim.id, "Scribbled on")

    seed_example_projects(shared_guest)
    assert next(p for p in list_for_user(shared_guest.id) if p.id == victim.id).name != "Scribbled on"
