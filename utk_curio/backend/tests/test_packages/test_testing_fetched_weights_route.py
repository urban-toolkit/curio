"""``/api/testing/fetched-weights``: a stand-in for the weights a model package's ``fetch`` names.

No CI run holds such weights, and no test may open a socket to download them,
so example 31's e2e plants a tiny SAM 3 in the catalog's copy of
``model.curio.sam3@1`` (``test_frontend/utils/stand_ins.py``). These tests
hold the door to what the docstring of the route promises:

- a plant lays the files out as ``scripts/fetch_model_weights.py`` leaves the
  real ones, each stamped with the digest the block names, so Curio reads
  them in place, resolves the model without a download, and the Model
  Catalog says nothing downloads on first use;
- a removal takes out what the plant wrote and nothing else, so the catalog's
  copy is as it was and the Model Catalog says the weights download on first
  use again;
- a plant is refused where real weights are in place, where
  ``--model-weights-dir`` names the folder of the weights, and for any other
  package or any other files than the block lists.

The stand-in's bytes here are a few of their own: the route reads none of
them, as Curio reads the stamps and never the weights.
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SAM3 = "model.curio.sam3@1"
ROUTE = "fetched-weights"


def _post(client, **body):
    return client.post(f"/api/testing/{ROUTE}", data=json.dumps(body), headers={"Content-Type": "application/json"})


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> Path:
    """A package catalog of its own, holding the shipped SAM 3 package as a
    clone holds it: its manifest names the weights, and none is there."""
    root = tmp_path / "catalog"
    root.mkdir()
    # A node package, and a model package whose weights ship, for the plants refused.
    for package in (SAM3, "curio.builtin@1", "model.curio.ddrnet23-slim@1"):
        shutil.copytree(REPO / "packages" / package, root / package, ignore=shutil.ignore_patterns("models"))
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    return root


def _manifest(folder: Path):
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    return load_package_manifest(folder)


def _stand_in(folder: Path) -> dict[str, bytes]:
    """Bytes of their own for each file the package's ``fetch`` lists."""
    return {item.path: f"stand-in for {item.path}\n".encode() for item in _manifest(folder).model.fetch.files}


def _plant(client, files: dict[str, bytes], dir_name: str = SAM3):
    return _post(client, action="plant", dirName=dir_name,
                 files={rel: base64.b64encode(data).decode("ascii") for rel, data in files.items()})


def _tree(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def test_a_plant_is_read_in_place_as_fetched_weights_and_a_removal_puts_the_package_back(client, catalog):
    from utk_curio.backend.app.packages.application import model_packages
    from utk_curio.backend.app.packages.domain.model_fetch import FILE_MODE, FOLDER_MODE, is_stamped

    package = catalog / SAM3
    before = _tree(package)
    manifest = _manifest(package)
    entry = package / manifest.model.entry
    files = _stand_in(package)
    assert model_packages.weights_on_first_use(manifest, package) is True

    planted = _plant(client, files)

    assert planted.status_code == 200, planted.get_json()
    assert planted.get_json() == {"planted": SAM3, "files": sorted(files)}
    for item in manifest.model.fetch.files:
        target = entry / item.path
        assert target.read_bytes() == files[item.path]
        assert is_stamped(target, item), f"{item.path} is not stamped with the digest the block names"
        assert target.stat().st_mode & 0o777 == FILE_MODE
    assert (entry.stat().st_mode & 0o777, entry.parent.stat().st_mode & 0o777) == (FOLDER_MODE, FOLDER_MODE)
    # Read in place: the catalog's copy holds them, and nothing downloads.
    assert model_packages.fetched_weights_folder(manifest, package.resolve()) == package.resolve()
    assert model_packages.weights_on_first_use(manifest, package) is False

    removed = _post(client, action="remove", dirName=SAM3)

    assert removed.status_code == 200, removed.get_json()
    assert removed.get_json() == {"removed": sorted(files), "dirName": SAM3}
    assert _tree(package) == before and not (package / "models").exists()
    assert model_packages.weights_on_first_use(manifest, package) is True


def test_a_planted_model_resolves_for_an_accounts_run_with_no_download(client, catalog, user_and_token, monkeypatch):
    """An account's copy of the package, as the examples' seeding gives every
    account, resolves its model to the catalog's copy, where the stand-in is,
    and no run downloads the weights."""
    from utk_curio.backend.app.packages.application import model_packages
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.infrastructure import fetched_weights
    from utk_curio.backend.app.projects import services as projects_services

    user, _token = user_and_token
    user_key = projects_services._user_dir_key(user)
    install_package_from_directory(user_key, catalog / SAM3)

    def no_download(*_args, **_kwargs):
        raise AssertionError("a run downloaded weights a plant put in place")

    monkeypatch.setattr(fetched_weights, "download", no_download)
    assert _plant(client, _stand_in(catalog / SAM3)).status_code == 200

    assert model_packages.resolve_model_dirs(user_key, ["model.curio.sam3"]) == {
        "model.curio.sam3": str((catalog / SAM3).resolve()),
    }
    assert model_packages.resolve_model_weights(user_key, ["model.curio.sam3"]) == {}


def test_a_plant_never_replaces_weights_in_place_and_a_removal_leaves_them(client, catalog):
    """A file the block lists, placed and stamped as a download places it,
    turns a plant away and stays as it was, and so does its stamp; a removal
    with no plant takes out nothing."""
    from utk_curio.backend.app.packages.domain.model_fetch import is_stamped, write_stamp

    package = catalog / SAM3
    manifest = _manifest(package)
    entry = package / manifest.model.entry
    item = manifest.model.fetch.files[0]
    entry.mkdir(parents=True)
    (entry / item.path).write_bytes(b"downloaded")
    write_stamp(entry / item.path, item)

    planted = _plant(client, _stand_in(package))
    removed = _post(client, action="remove", dirName=SAM3)

    assert planted.status_code == 409, planted.get_json()
    assert item.path in planted.get_json()["error"]
    assert removed.get_json() == {"removed": [], "dirName": SAM3}
    assert (entry / item.path).read_bytes() == b"downloaded" and is_stamped(entry / item.path, item)
    assert sorted(path.name for path in entry.iterdir()) == sorted([item.path, f".{item.path}.digest"])


def test_a_removal_leaves_a_file_no_longer_as_planted(client, catalog):
    """A file a download put in a planted one's place stays where it is when
    the plant is taken out, with the folders that hold it."""
    package = catalog / SAM3
    manifest = _manifest(package)
    entry = package / manifest.model.entry
    files = _stand_in(package)
    assert _plant(client, files).status_code == 200
    kept = manifest.model.fetch.files[-1].path
    (entry / kept).write_bytes(b"downloaded since")

    removed = _post(client, action="remove", dirName=SAM3)

    assert removed.get_json()["removed"] == sorted(set(files) - {kept})
    assert (entry / kept).read_bytes() == b"downloaded since"
    assert not (entry / ".curio-test-planted.json").exists()


def test_a_plant_is_refused_where_model_weights_dir_names_the_folder_of_the_weights(
    client, catalog, tmp_path, monkeypatch,
):
    monkeypatch.setenv("CURIO_MODEL_WEIGHTS_DIR", str(tmp_path / "weights"))

    planted = _plant(client, _stand_in(catalog / SAM3))

    assert planted.status_code == 409, planted.get_json()
    assert "--model-weights-dir" in planted.get_json()["error"]
    assert not (catalog / SAM3 / "models").exists() and not (tmp_path / "weights").exists()


def test_only_every_file_the_fetch_lists_is_planted_and_only_for_a_package_that_fetches(client, catalog):
    files = _stand_in(catalog / SAM3)
    first = sorted(files)[0]
    one_short = _plant(client, {rel: data for rel, data in files.items() if rel != first})
    one_more = _plant(client, {**files, "extra.bin": b"\x00"})
    not_base64 = _post(client, action="plant", dirName=SAM3, files={rel: "not base64!" for rel in files})
    shipped_weights = _plant(client, {"model.onnx": b"\x00"}, dir_name="model.curio.ddrnet23-slim@1")
    node_package = _plant(client, {"model.onnx": b"\x00"}, dir_name="curio.builtin@1")
    unknown = _plant(client, files, dir_name="model.curio.nothing@1")
    not_a_package = _plant(client, files, dir_name="../model.curio.sam3@1")
    bad_action = _post(client, action="replace", dirName=SAM3)

    assert [r.status_code for r in (one_short, one_more, not_base64)] == [400, 400, 400]
    assert [r.status_code for r in (shipped_weights, node_package, unknown, not_a_package, bad_action)] == [
        400, 400, 404, 400, 400,
    ]
    assert not (catalog / SAM3 / "models").exists()
