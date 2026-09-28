"""Installing a file already on disk, without reading it into memory.

``_install_imported_path`` is the path-taking sibling of
``_install_imported_bytes``. It must give the same answer for the same file:
the same stored bytes, the same recorded encoding, the same counts and item.
The transcode it relies on streams, so the parity is checked against
``to_utf8`` on the cases that went wrong before (#280, #368), including the
ones that turn on a byte offset.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datasets.infrastructure import text_encoding
from utk_curio.backend.app.datasets.infrastructure.text_encoding import (
    SNIFF_BYTES,
    TextDecodeError,
    to_utf8,
    transcode_file_to_utf8,
)

BOM = b"\xef\xbb\xbf"

SAMPLES = {
    "empty": b"",
    "ascii": b"city,note\nChicago,loop\n",
    "utf8": "city,note\nCafé,naïve\n".encode("utf-8"),
    "utf8 with a BOM": BOM + "city\nZürich\n".encode("utf-8"),
    "cp1252": "city,note\nCafé,naïve\nZürich,Öl\n".encode("cp1252"),
    "accent past the window": b"A" * SNIFF_BYTES + b"\xe9,x\n",
    "accent far past the window": b"A" * (SNIFF_BYTES * 4) + b"\xe9,x\n",
    "a BOM, then an accent past the window": BOM + b"A" * (SNIFF_BYTES * 2) + b"\xe9,x\n",
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_the_stream_agrees_with_the_whole_buffer_transcode(tmp_path, name):
    data = SAMPLES[name]
    src, dest = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_bytes(data)

    expected, expected_encoding = to_utf8(data, what=name)
    encoding = transcode_file_to_utf8(src, dest, what=name)

    assert encoding == expected_encoding
    assert dest.read_bytes() == expected


def test_a_character_split_across_chunks_is_still_utf8(tmp_path, monkeypatch):
    """A three-byte character straddling a chunk boundary is not an error."""
    monkeypatch.setattr(text_encoding, "STREAM_CHUNK_BYTES", 7)
    data = ("abcde€" * 50).encode("utf-8")
    src, dest = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_bytes(data)
    assert transcode_file_to_utf8(src, dest) == "utf-8"
    assert dest.read_bytes() == data


def test_an_invalid_byte_is_located_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(text_encoding, "STREAM_CHUNK_BYTES", 5)
    data = "ab€".encode("utf-8") * 20 + b"\xe9" + b"tail"
    path = tmp_path / "in.csv"
    path.write_bytes(data)
    assert text_encoding._first_invalid_utf8(path) == data.index(b"\xe9")


@pytest.fixture()
def mutations(app, user_and_token):
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user, _token = user_and_token
    return DatasetCatalogService(user)._mutations


def test_a_path_install_matches_a_bytes_install(mutations, tmp_path):
    body = SAMPLES["cp1252"]
    by_bytes = mutations._install_imported_bytes(body, "cities.csv", "csv", title="Cities")
    src = tmp_path / "cities.csv.part"
    src.write_bytes(body)
    by_path = mutations._install_imported_path(src, "cities.csv", "csv", title="Cities")

    for key in ("format", "rowCount", "featureCount", "sourceEncoding", "title", "origin"):
        assert by_path[key] == by_bytes[key], key
    assert by_path["id"] != by_bytes["id"]
    from pathlib import Path

    assert Path(by_path["path"]).read_bytes() == Path(by_bytes["path"]).read_bytes()
    assert "curio_dataset_path(" in by_path["loaderSnippet"]["code"]


def test_a_path_install_consumes_its_source(mutations, tmp_path):
    src = tmp_path / "table.parquet.part"
    src.write_bytes(b"PAR1-not-really-parquet")
    item = mutations._install_imported_path(src, "table.parquet", "parquet")
    assert not src.exists()
    assert item["format"] == "parquet"


def test_an_undecodable_path_install_is_a_catalog_error(mutations, tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

    def refuse(src, dest, *, what):
        raise TextDecodeError(f"Could not read {what} as text")

    monkeypatch.setattr(text_encoding, "transcode_file_to_utf8", refuse)
    src = tmp_path / "bad.csv.part"
    src.write_bytes(b"x\n")
    with pytest.raises(DatasetCatalogError, match="Could not read bad.csv"):
        mutations._install_imported_path(src, "bad.csv", "csv")
