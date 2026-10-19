"""``downloadOnFirstUse`` in a dataset manifest: the data file the pip package leaves out.

A dataset that ships with Curio and whose data file is too big for the pip
package names that file in its manifest. The release leaves it out
(``setup.py``), and a pip install downloads it from GitHub the first time
Curio reads the dataset (``datasets/infrastructure/left_out_files.py``).

- The parser keeps the field, and refuses what no reader would download:
  anything but a list of paths in the dataset's folder, and any path but the
  dataset's ``dataFile``.
- The writer writes it only for a dataset that names one, and reads back what
  it wrote.
- Every shipped dataset that names one parses, and holds the file.

The code under test is imported inside each test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.tests._support.left_out_files import EXPECTED

REPO = Path(__file__).resolve().parents[4]
DATA_FILE = "data/big.parquet"


def _raw(**fields) -> dict:
    raw = {
        "id": "data.test.big", "name": "Big", "version": "1.0.0", "format": "parquet",
        "dataFile": DATA_FILE, "compatibility": {"major": 1},
    }
    raw.update(fields)
    return raw


def _parse(raw: dict):
    from utk_curio.backend.app.datasets.domain.manifest import _parse_manifest

    return _parse_manifest(raw, where="manifest.json")


def test_a_dataset_names_its_data_file():
    assert _parse(_raw(downloadOnFirstUse=[DATA_FILE])).download_on_first_use == (DATA_FILE,)
    assert _parse(_raw()).download_on_first_use == ()
    assert _parse(_raw(downloadOnFirstUse=[])).download_on_first_use == ()


@pytest.mark.parametrize("value, words", [
    (DATA_FILE, "list"),
    ({"path": DATA_FILE}, "list"),
    ([3], "path inside"),
    ([""], "path inside"),
    (["/data/big.parquet"], "path inside"),
    (["data\\big.parquet"], "path inside"),
    (["data/../big.parquet"], "path inside"),
    (["./data/big.parquet"], "path inside"),
    (["data//big.parquet"], "path inside"),
    (["manifest.json"], "always ships"),
    ([DATA_FILE, DATA_FILE], "twice"),
    (["data/other.parquet"], "dataFile"),
    (["data"], "dataFile"),
])
def test_a_dataset_manifest_refuses_what_no_reader_would_download(value, words):
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError

    with pytest.raises(ManifestError, match="downloadOnFirstUse") as raised:
        _parse(_raw(downloadOnFirstUse=value))
    assert words in str(raised.value), str(raised.value)


def test_the_writer_writes_it_only_for_a_dataset_that_names_one():
    from utk_curio.backend.app.datasets.domain.manifest import build_manifest_dict

    named = build_manifest_dict(_parse(_raw(downloadOnFirstUse=[DATA_FILE])))
    assert named["downloadOnFirstUse"] == [DATA_FILE]
    assert _parse(named).download_on_first_use == (DATA_FILE,)
    assert "downloadOnFirstUse" not in build_manifest_dict(_parse(_raw()))


def test_every_shipped_dataset_that_names_a_file_parses_and_holds_it():
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

    named = []
    for folder in sorted(path.parent for path in (REPO / "datasets").glob("*/manifest.json")):
        manifest = load_dataset_manifest(folder)
        for rel in manifest.download_on_first_use:
            assert (folder / rel).is_file(), f"{folder.name} names {rel}, which it does not hold"
            named.append(f"datasets/{folder.name}/{rel}")
    assert sorted(named) == sorted(path for path in EXPECTED if path.startswith("datasets/"))
