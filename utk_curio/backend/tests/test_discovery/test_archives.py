"""What a downloaded archive holds, read without trusting it (#608).

The download tests in ``test_acquire.py`` run these through the whole stack;
these pin the edges of :mod:`discovery.application.archives` directly, on
archives built here.
"""

from __future__ import annotations

import gzip
import io
import zipfile

import pytest

from utk_curio.backend.app.discovery.domain.errors import UnsupportedFormatError


def _zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _unpack(kind, path, tmp_path, name="download"):
    from utk_curio.backend.app.discovery.application import archives

    work = tmp_path / "work"
    work.mkdir()
    return archives.unpack(kind, path, name=name, work=work)


def test_a_backslash_between_folders_is_read_as_one(tmp_path):
    """Some Windows tools write ``folder\\file``; it is a folder, not a refusal."""
    from utk_curio.backend.app.discovery.application import archives

    path = _zip(tmp_path / "a.zip", {"data\\tracts.csv": b"id\n1\n", "data\\readme.txt": b"x"})
    found = _unpack("zip", path, tmp_path)
    assert isinstance(found, archives.SingleFile)
    assert found.name == "tracts.csv"
    assert found.path.read_bytes() == b"id\n1\n"
    # Written under a name Curio minted, inside the folder it was given.
    assert found.path.parent == tmp_path / "work"


def test_a_backslash_that_climbs_out_is_refused(tmp_path):
    path = _zip(tmp_path / "a.zip", {"..\\escape.csv": b"id\n1\n"})
    with pytest.raises(UnsupportedFormatError, match="'..'"):
        _unpack("zip", path, tmp_path)


def test_a_concatenated_gzip_is_one_file(tmp_path):
    """``gunzip`` reads every member of a gzip file as one file, and so does Curio."""
    from utk_curio.backend.app.discovery.application import archives

    path = tmp_path / "wac.csv.gz"
    path.write_bytes(gzip.compress(b"id\n1\n") + gzip.compress(b"2\n"))
    found = _unpack("gzip", path, tmp_path, name="wac.csv")
    assert isinstance(found, archives.SingleFile)
    assert found.path.read_bytes() == b"id\n1\n2\n"


def test_a_truncated_gzip_is_refused(tmp_path):
    path = tmp_path / "wac.csv.gz"
    path.write_bytes(gzip.compress(b"id\n" + b"1\n" * 1000)[:-12])
    with pytest.raises(UnsupportedFormatError, match="ends before its gzip stream does"):
        _unpack("gzip", path, tmp_path, name="wac.csv")


def test_a_gzip_holding_a_zip_is_refused(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("a.csv", b"id\n1\n")
    path = tmp_path / "data.gz"
    path.write_bytes(gzip.compress(inner.getvalue()))
    with pytest.raises(UnsupportedFormatError, match="another archive"):
        _unpack("gzip", path, tmp_path, name="data")


def test_a_shapefile_needs_its_dbf_and_shx(tmp_path):
    path = _zip(tmp_path / "a.zip", {"roads.shp": b"\x00" * 100, "roads.prj": b"x"})
    with pytest.raises(UnsupportedFormatError, match=r"needs its \.dbf and \.shx"):
        _unpack("zip", path, tmp_path)


def test_an_archive_of_documentation_only_says_so(tmp_path):
    path = _zip(tmp_path / "a.zip", {"readme.txt": b"x", "terms.pdf": b"%PDF"})
    with pytest.raises(UnsupportedFormatError, match="holds no file Curio can add"):
        _unpack("zip", path, tmp_path)


def test_stops_alone_is_not_a_gtfs_feed(tmp_path):
    """``stops.txt`` with no other GTFS table is a text file, and text files
    are documentation."""
    path = _zip(tmp_path / "a.zip", {"stops.txt": b"stop_id\n1\n"})
    with pytest.raises(UnsupportedFormatError, match="holds no file Curio can add"):
        _unpack("zip", path, tmp_path)
