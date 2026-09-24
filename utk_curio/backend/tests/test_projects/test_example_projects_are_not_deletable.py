"""An example dataflow Curio seeded cannot be deleted.

The Data Catalog has hidden Delete for anything that came from the shared
catalog for a while: what the deployment shipped is yours to use, not to
remove. Dataflows never had the equivalent - ``projectActions`` took no state,
so every card in the projects list offered Delete, the eleven seeded examples
included.

That was survivable while a back-fill put them back. It stopped being
survivable in #270, which keyed the seeding marker to the account precisely so
that "an example the user deliberately deleted must stay deleted" - after which
one mis-click removed a shipped example from that account permanently, with no
restore route anywhere in the product.

So: the list marks them (``is_example``) and the page withholds Delete, and
these cases cover the half that holds when the request does not come from the
page.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.repositories import list_for_user
from utk_curio.backend.app.projects.schemas import ProjectCreate
from utk_curio.backend.app.projects.seed import (
    _example_files,
    _example_id,
    _repo_root,
    example_project_ids,
    is_example_project,
    seed_example_projects,
)


def _example_stems() -> list[str]:
    return [p.stem for p in _example_files(_repo_root() / "docs" / "examples")]


def _my_own_project(user):
    """A project the user made, to stand next to the seeded ones."""
    spec = {"dataflow": {"name": "My own dataflow", "nodes": [], "edges": []}}
    return services.save_project(
        user, ProjectCreate(name="My own dataflow", spec=spec, outputs=[])
    )


@pytest.fixture(autouse=True)
def examples_enabled(monkeypatch):
    """The seed is gated on the launcher's ``--with-examples`` flag."""
    monkeypatch.setenv("CURIO_SEED_EXAMPLES", "1")


def test_deleting_a_seeded_example_is_refused(app, db, user_and_token):
    user, _ = user_and_token
    assert seed_example_projects(user) == len(_example_stems())

    example = list_for_user(user.id)[0]
    with pytest.raises(services.ProjectError) as exc:
        services.delete_project(user, example.id)

    assert exc.value.status == 403
    # Nothing was half-done on the way to the refusal: the row and its spec are
    # both still there. The guard sits before ``delete_tree``.
    assert any(p.id == example.id for p in list_for_user(user.id))
    assert storage.read_spec(str(user.id), example.id) is not None


def test_a_project_the_user_made_still_deletes(app, db, user_and_token):
    """The guard is narrow: it names example ids, not "anything seeded-looking"."""
    user, _ = user_and_token
    seed_example_projects(user)

    mine = _my_own_project(user)
    services.delete_project(user, mine.id)

    assert not any(p.id == mine.id for p in list_for_user(user.id))


def test_the_listing_marks_which_rows_are_examples(app, db, user_and_token):
    """What the page reads to decide whether to offer Delete at all."""
    user, _ = user_and_token
    seed_example_projects(user)
    mine = _my_own_project(user)

    summaries = services.list_projects(user)
    by_id = {s.id: s for s in summaries}

    assert by_id[mine.id].is_example is False
    examples = [s for s in summaries if s.id != mine.id]
    assert examples, "no seeded examples in the listing"
    assert all(s.is_example is True for s in examples)


def test_the_example_set_is_derived_per_account(app, db, user_and_token):
    """Two accounts' examples occupy different ids, so neither guards the other.

    ``_example_id`` has been account-scoped since #200 (a global PK made the
    second user's seed collide). The guard has to follow that scoping, or one
    user's ordinary project could share an id with another's example.
    """
    user, _ = user_and_token
    stems = _example_stems()

    ids = example_project_ids(user)
    assert ids == {_example_id(stem, user) for stem in stems}
    assert all(is_example_project(user, pid) for pid in ids)

    # A project id that is not in the set is not protected.
    assert not is_example_project(user, "00000000-0000-0000-0000-000000000000")


def test_the_guard_does_not_need_the_examples_to_be_seeded_yet(
    app, db, user_and_token
):
    """The ids are read off disk, so the answer does not depend on DB state."""
    user, _ = user_and_token
    # Nothing seeded in this test at all.
    assert list_for_user(user.id) == []
    assert len(example_project_ids(user)) == len(_example_stems())
