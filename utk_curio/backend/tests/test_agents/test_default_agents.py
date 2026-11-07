"""The agents every account has by default (``lifecycle.seed_default_agents``).

They are the catalog cards Curio ships: each agent whose manifest says
``catalog.listed``. An account gets them in My Imports and in every dataflow
it has or makes, the examples Curio seeds for it among them, and so does the
shared guest, whose hosted visitors' copies are made from its examples. An
agent the account removes from all its projects stays out; one Curio ships
later still arrives. Each test imports what main lacks inside itself, so a
checkout without the defaults fails here test by test."""

from __future__ import annotations

from utk_curio.backend import config
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

#: Two visitors' sign-ins to the shared guest account.
VISITOR_A = "default-agents-visitor-a"
VISITOR_B = "default-agents-visitor-b"
EMPTY = {"dataflow": {"nodes": [], "edges": [], "packages": []}}


def _listed() -> list[str]:
    """The catalog cards Curio ships, by their manifests, sorted as a
    lockfile holds them."""
    return sorted(m.dir_name for m in builtin.list_builtin_manifests() if m.catalog.listed)


def _helpers() -> list[str]:
    return sorted(m.dir_name for m in builtin.list_builtin_manifests() if not m.catalog.listed)


def _required_by_none() -> list[str]:
    """The listed agents no other listed agent requires: Remove from all
    projects takes each out of every dataflow at once."""
    required = {
        agent_id for coord in _listed() for agent_id in builtin.get_builtin_manifest(coord).requires_agents
    }
    free = [coord for coord in _listed() if coord.split("@", 1)[0] not in required]
    assert free, "every listed agent is required by another, so none can be removed alone"
    return free


def _create(client, token: str, name: str = "p") -> str:
    created = client.post("/api/projects", json={"name": name, "spec": EMPTY, "outputs": []},
                          headers=_auth(token))
    assert created.status_code == 201, created.get_data(as_text=True)
    return created.get_json()["id"]


def _lockfile(user_key: str, project_id: str) -> list[str]:
    return project_agents.project_agents(storage.read_spec(user_key, project_id))


def _palette(client, token: str, project_id: str) -> list[str]:
    """What the canvas's agents palette lists for the dataflow."""
    listed = client.get(f"/api/agents/projects/{project_id}", headers=_auth(token))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    return [card["dirName"] for card in listed.get_json()["agents"]]


def _imports(client, token: str) -> list[str]:
    listed = client.get("/api/agents/imports", headers=_auth(token))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    return [card["dirName"] for card in listed.get_json()["agents"]]


def _shared_guest(db):
    """The shared guest account, signed in as two visitors."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_A))
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_B))
    db.session.commit()
    return guest


def test_a_new_dataflow_holds_exactly_the_listed_agents_and_no_helper(client, new_account_and_token, tmp_curio):
    from utk_curio.backend.app.agents.service import default_agent_coords  # noqa: F401 - what main lacks

    user, token = new_account_and_token
    assert _listed() and _helpers(), "the roster ships no catalog card or no helper, so this proves nothing"

    project_id = _create(client, token)

    assert _lockfile(_user_dir_key(user), project_id) == _listed()
    assert _palette(client, token, project_id) == _listed()
    assert not set(_lockfile(_user_dir_key(user), project_id)) & set(_helpers())
    # And the catalog reads each card as in all projects, this one among them.
    cards = client.get(f"/api/agents/catalog?projectId={project_id}", headers=_auth(token)).get_json()["agents"]
    by_coord = {card["dirName"]: card for card in cards}
    for coord in _listed():
        assert by_coord[coord]["imported"] is True, coord
        assert by_coord[coord]["installedInProject"] is True, coord


def test_the_dataflows_an_account_had_get_them_at_its_next_listing(client, new_account_and_token, tmp_curio):
    """An account that had dataflows before Curio added the agents by default
    gets them in each, as Add to all projects puts an agent there."""
    from utk_curio.backend.app.agents.repositories import imports

    user, token = new_account_and_token
    key = _user_dir_key(user)
    project_id = _create(client, token)
    # As the account was before: no agent recorded, none in its dataflow.
    imports.save_imported_agents(key, [], seeded=[])
    spec = storage.read_spec(key, project_id)
    project_agents.set_project_agents(spec, [])
    storage.write_spec(key, project_id, spec)
    assert _lockfile(key, project_id) == []

    assert _imports(client, token) == _listed()
    assert _lockfile(key, project_id) == _listed()


def test_a_seeded_example_holds_them(client, new_account_and_token, tmp_curio):
    from utk_curio.backend.app.projects import seed

    user, _token = new_account_and_token
    example = seed.shipped_dataflows()[0]
    assert seed.seed_example_projects(user, prune=False, overwrite=False, only_keys=[example.key]) == 1

    project_id = seed._example_id(example.key, user)
    assert _lockfile(_user_dir_key(user), project_id) == _listed()


def test_the_shared_guests_examples_get_them_each_time_they_are_put_back(client, db, tmp_curio):
    from utk_curio.backend.app.projects import seed

    guest = _shared_guest(db)
    example = seed.shipped_dataflows()[0]
    project_id = seed._example_id(example.key, guest)
    for _start in range(2):
        assert seed.seed_example_projects(guest, only_keys=[example.key]) == 1
        assert _lockfile(GUEST_KEY, project_id) == _listed()


def test_a_hosted_guests_copy_of_an_example_holds_them(client, db, tmp_curio, monkeypatch):
    from utk_curio.backend.app.projects import seed, visitor_copies

    guest = _shared_guest(db)
    example = seed.shipped_dataflows()[0]
    assert seed.seed_example_projects(guest, only_keys=[example.key]) == 1
    project_id = seed._example_id(example.key, guest)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)  # Curio is hosted: the visitors are hosted guests

    # A request of the visitor's that writes makes the visitor's own copy.
    made = client.post(f"/api/agents/projects/{project_id}/install",
                       json={"coord": _required_by_none()[0]}, headers=_auth(VISITOR_A))
    assert made.status_code == 201, made.get_data(as_text=True)
    copy = visitor_copies.copy_id(VISITOR_A, project_id)
    assert (storage.project_dir(GUEST_KEY, copy) / visitor_copies.VISITOR_FILE).is_file()

    assert _lockfile(GUEST_KEY, copy) == _listed()
    assert _palette(client, VISITOR_A, project_id) == _listed()
    assert _palette(client, VISITOR_B, project_id) == _listed()


def test_a_hosted_guest_gets_them_though_it_may_not_add_or_remove_agents(client, db, tmp_curio, monkeypatch):
    """Curio adds them, not the visitor, so the refusal of a hosted guest's
    imports and removals does not stop them."""
    _shared_guest(db)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    coord = _required_by_none()[0]

    assert _imports(client, VISITOR_A) == _listed()
    added = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(VISITOR_A))
    assert added.status_code == 403, added.get_data(as_text=True)
    removed = client.delete(f"/api/agents/imports/{coord}", headers=_auth(VISITOR_B))
    assert removed.status_code == 403, removed.get_data(as_text=True)
    assert _imports(client, VISITOR_B) == _listed()


def test_an_agent_removed_from_all_projects_stays_removed(client, new_account_and_token, tmp_curio):
    user, token = new_account_and_token
    gone = _required_by_none()[0]
    kept = [coord for coord in _listed() if coord != gone]
    first = _create(client, token, "first")

    removed = client.delete(f"/api/agents/imports/{gone}", headers=_auth(token))
    assert removed.status_code == 200, removed.get_data(as_text=True)

    # Every listing after it, the ones that add the defaults among them.
    assert _imports(client, token) == kept
    assert _palette(client, token, first) == kept
    cards = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
    assert next(card for card in cards if card["dirName"] == gone)["imported"] is False
    assert _imports(client, token) == kept
    # And a dataflow made after it.
    second = _create(client, token, "second")
    assert _lockfile(_user_dir_key(user), second) == kept
    assert _palette(client, token, first) == kept


def test_an_agent_listed_later_arrives_for_an_account_that_had_the_others(
    client, new_account_and_token, tmp_curio, monkeypatch,
):
    """The account had the defaults before one more card shipped, and had
    removed one of them: the new card arrives in My Imports and in its
    dataflows, and the removed one stays out. The new card requires no other
    agent, so its install brings in nothing the account removed."""
    user, token = new_account_and_token
    key = _user_dir_key(user)
    free = _required_by_none()
    later = next(coord for coord in free if not builtin.get_builtin_manifest(coord).requires_agents)
    out = next(coord for coord in free if coord != later)
    shipped = builtin.list_builtin_manifests
    monkeypatch.setattr(builtin, "list_builtin_manifests",
                        lambda: [m for m in shipped() if m.dir_name != later])
    before = [coord for coord in _listed() if coord != later]
    project_id = _create(client, token)
    assert _lockfile(key, project_id) == before
    removed = client.delete(f"/api/agents/imports/{out}", headers=_auth(token))
    assert removed.status_code == 200, removed.get_data(as_text=True)
    held = [coord for coord in before if coord != out]
    assert _imports(client, token) == held

    monkeypatch.setattr(builtin, "list_builtin_manifests", shipped)  # the card ships

    now = sorted([*held, later])
    assert _imports(client, token) == now
    assert _lockfile(key, project_id) == now
    assert _palette(client, token, project_id) == now
