"""The example-dataset seeder: discovery, provisioning, and idempotence.

The seeder is what makes a committed ``dataflow.datasets`` ref *real* on this
machine. Without it the ref still resolves for execution (the hub row wins the
catalog dedupe), so nothing fails loudly - the Data palette just quietly renders
``dirName``-titled rows with a wrong ``csv`` chip and no row count. That failure
mode is invisible to every other test in this suite, which is why these are
worth having.

Run::

    python -m pytest utk_curio/backend/tests/test_datasets/test_example_dataset_seed.py -v
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.datasets.infrastructure.storage import (
    catalog_root,
    dataset_dir,
)
from utk_curio.backend.app.datasets.seed import (
    ensure_user_datasets_initialized,
    example_dep_dataset_dirs,
    seed_example_datasets,
)

USER_KEY = "guest"


def _declared_from_disk() -> set[str]:
    """The union of ``dataflow.datasets[].dirName`` across the committed examples.

    Computed independently of the function under test, so the assertion compares
    two readings of the same source rather than a function against itself.
    """
    from pathlib import Path

    examples = Path(__file__).resolve().parents[4] / "docs" / "examples"
    found: set[str] = set()
    for path in examples.glob("*.json"):
        spec = json.loads(path.read_text(encoding="utf-8"))
        for ref in spec.get("dataflow", {}).get("datasets") or []:
            if ref.get("dirName"):
                found.add(ref["dirName"])
    return found


def test_discovery_matches_what_the_examples_declare():
    """Derived from the committed specs, with no hardcoded allowlist.

    The same property ``packages/seed.py::example_dep_package_ids`` relies on: a
    dataset added to an example is provisioned without anyone remembering to
    update the seeder.
    """
    assert set(example_dep_dataset_dirs()) == _declared_from_disk()


def test_every_declared_dataset_exists_in_the_committed_catalog():
    """A ref naming a directory that does not ship is a broken example.

    The seeder tolerates this at runtime (logs and moves on, so one bad ref
    cannot cost the others), which means only a test can catch it.
    """
    missing = [
        dir_name
        for dir_name in example_dep_dataset_dirs()
        if not (catalog_root() / dir_name / "manifest.json").is_file()
    ]
    assert not missing, (
        f"examples declare {missing}, which are not in the committed catalog at "
        f"{catalog_root()}"
    )


def test_declared_dirs_are_addressable_ids_plus_a_major():
    """``dirName`` is ``<id>@<major>``; ``curio_dataset_path`` takes the bare id.

    Getting this wrong is silent - ``SAFE_DATASET_ID_RE`` permits ``@``, so an
    id with the major appended passes validation, misses the by-id lookup in
    ``resolve_execution_paths``, and surfaces only as a sandbox runtime error.
    """
    for dir_name in example_dep_dataset_dirs():
        dataset_id, _, major = dir_name.rpartition("@")
        assert dataset_id and major.isdigit(), dir_name
        assert "@" not in dataset_id, dir_name


@pytest.mark.usefixtures("app")
def test_seeding_copies_every_declared_dataset_into_the_user_store():
    declared = example_dep_dataset_dirs()
    assert declared, "no example declares a dataset; this test would be vacuous"

    seeded = seed_example_datasets(USER_KEY)

    assert sorted(seeded) == sorted(declared)
    for dir_name in declared:
        store = dataset_dir(USER_KEY, dir_name)
        assert (store / "manifest.json").is_file(), dir_name
        manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
        data_file = store / manifest["dataFile"]
        assert data_file.is_file(), f"{dir_name} copied without its data file"
        assert data_file.stat().st_size > 0, f"{dir_name} data file is empty"


@pytest.mark.usefixtures("app")
def test_seeding_twice_is_a_no_op():
    """A steady-state boot must not re-copy tens of MB on every startup."""
    first = seed_example_datasets(USER_KEY)
    assert first, "first call copied nothing"

    sample = dataset_dir(USER_KEY, first[0])
    manifest = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    stamp = (sample / manifest["dataFile"]).stat().st_mtime_ns

    assert seed_example_datasets(USER_KEY) == []
    assert (sample / manifest["dataFile"]).stat().st_mtime_ns == stamp, (
        "the second seed rewrote the data file instead of skipping it"
    )


@pytest.mark.usefixtures("app")
def test_a_partial_install_is_repaired():
    """A previous failed copy must not leave a permanently broken dataset.

    ``install_dataset_from_catalog`` treats a destination whose data file is
    missing as not installed and starts fresh; without that, an interrupted
    first boot would leave a manifest with no bytes behind it and the palette
    would show a dataset that cannot load.
    """
    dir_name = example_dep_dataset_dirs()[0]
    seed_example_datasets(USER_KEY)

    store = dataset_dir(USER_KEY, dir_name)
    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    data_file = store / manifest["dataFile"]
    data_file.unlink()

    assert dir_name in seed_example_datasets(USER_KEY)
    assert data_file.is_file(), "the partial install was not repaired"


@pytest.mark.usefixtures("app")
def test_a_dataset_missing_from_the_catalog_is_skipped_not_fatal(monkeypatch):
    """One unresolvable ref must not stop the rest from being provisioned.

    Seeding runs on the startup path and inside ``load_project``; a hard failure
    there would take down a boot or a project open over a cosmetic problem.
    """
    declared = example_dep_dataset_dirs()
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.seed.example_dep_dataset_dirs",
        lambda: ("data.nonexistent.nothing@1", *declared),
    )

    seeded = seed_example_datasets(USER_KEY)

    assert "data.nonexistent.nothing@1" not in seeded
    assert sorted(seeded) == sorted(declared)


@pytest.mark.usefixtures("app")
def test_the_per_user_hook_never_raises(monkeypatch):
    """``ensure_user_datasets_initialized`` is called from ``load_project``.

    It must swallow everything: a seeding problem is a degraded palette, never a
    failed project open. Same contract as
    ``packages/services.py::ensure_user_packages_initialized``.
    """
    def boom(_user_key):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.seed.seed_example_datasets", boom
    )
    ensure_user_datasets_initialized(USER_KEY)  # must not raise


@pytest.mark.usefixtures("app")
def test_seeded_datasets_carry_their_real_metadata():
    """The whole point of the copy, asserted directly.

    A ref with no store copy yields a placeholder whose title is the raw
    ``dirName`` and whose format defaults to ``csv``. After seeding, the store
    manifest is the real one - so this is the difference between a palette row
    reading "Chicago Green Roofs / geojson / 61 features" and one reading
    "data.urbanlab.chicago-boundary@1 / csv / (nothing)".
    """
    seed_example_datasets(USER_KEY)

    for dir_name in example_dep_dataset_dirs():
        store = dataset_dir(USER_KEY, dir_name)
        manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["name"], dir_name
        assert manifest["name"] != dir_name, (
            f"{dir_name}: name is the directory name, so the palette would show "
            f"no real title"
        )
        assert manifest["format"] in {
            "csv",
            "geojson",
            "json",
            "parquet",
            "geotiff",
            "shp",
            "bundle",
        }, manifest["format"]


@pytest.mark.usefixtures("app")
def test_a_parquet_dataset_keeps_its_decode_sidecar_through_the_copy():
    """The sidecar is what restores JSON-encoded object columns on load.

    A hub install is a whole-directory ``copytree``, so the sidecar rides along
    for free - but only as long as it lives inside the dataset directory. If it
    ever moved, ``loader_snippet("parquet")`` would silently return ``tags`` and
    ``validations`` as JSON strings instead of lists.
    """
    seed_example_datasets(USER_KEY)

    checked = 0
    for dir_name in example_dep_dataset_dirs():
        source = catalog_root() / dir_name
        for sidecar in source.rglob("*.decode.json"):
            copied = dataset_dir(USER_KEY, dir_name) / sidecar.relative_to(source)
            assert copied.is_file(), f"{dir_name}: {sidecar.name} was not copied"
            assert copied.read_bytes() == sidecar.read_bytes()
            checked += 1
    assert checked, (
        "no parquet decode sidecar found in any declared dataset; this test "
        "would be vacuous (expected one for the Project Sidewalk labels)"
    )


@pytest.mark.usefixtures("app")
def test_seeding_survives_a_catalog_directory_it_cannot_read(tmp_path, monkeypatch):
    """An unreadable manifest is skipped, not fatal.

    Same tolerance as the missing-directory case, exercised through a real
    malformed manifest rather than a name that does not exist.
    """
    broken_root = tmp_path / "broken-catalog"
    broken_root.mkdir()
    broken = broken_root / "data.broken.thing@1"
    (broken / "data").mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")

    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(broken_root))
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.seed.example_dep_dataset_dirs",
        lambda: ("data.broken.thing@1",),
    )

    assert seed_example_datasets(USER_KEY) == []


def test_the_examples_and_the_seeder_agree_on_dataset_count():
    """A sanity check on scale, so a wholesale loss of refs is loud.

    If someone regenerates the example specs through a path that drops
    ``dataflow.datasets`` (the client used to overwrite it before
    ``ref_ownership.preserve_dataset_refs``), discovery silently returns fewer
    entries and every example quietly reverts to hub-only browsing.
    """
    assert len(example_dep_dataset_dirs()) >= 9, (
        f"only {len(example_dep_dataset_dirs())} dataset(s) declared across the "
        f"examples; the migration landed 9"
    )


@pytest.mark.usefixtures("app")
def test_opening_a_project_provisions_the_example_datasets(client, user_and_token, tmp_path, monkeypatch):
    """The wiring, not just the function: ``GET /api/projects/<id>`` seeds.

    ``load_project`` is where a real signed-in user first touches the dataset
    system, and the startup seeder only ever covers ``guest``. Without this hook
    a user could open a seeded example and get a palette of ``dirName``-titled
    placeholders. Asserted through the route so that removing the call from
    ``projects/services.py`` fails a test rather than just degrading the UI.
    """
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        create_project,
    )

    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    user_key = _user_dir_key(user)

    declared = example_dep_dataset_dirs()
    assert declared, "no example declares a dataset; this test would be vacuous"
    assert not dataset_dir(user_key, declared[0]).exists(), (
        "the store should start empty for a fresh user"
    )

    project_id = create_project(client, token, name="Opens and seeds")
    resp = client.get(
        f"/api/projects/{project_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    for dir_name in declared:
        store = dataset_dir(user_key, dir_name)
        assert (store / "manifest.json").is_file(), (
            f"{dir_name} was not provisioned by opening a project; is "
            f"ensure_user_datasets_initialized still called from load_project?"
        )
