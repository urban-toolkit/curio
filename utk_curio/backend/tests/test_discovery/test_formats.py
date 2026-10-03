"""The format ladder, and the filenames it is handed.

Getting this wrong is not cosmetic: the format decides which loader the Data
Catalog generates, so a GeoJSON filed as ``json`` gives the user a node that
returns a dict where they expected a GeoDataFrame.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.discovery.domain.errors import UnsupportedFormatError
from utk_curio.backend.app.discovery.domain.formats import (
    resolve_format,
    safe_remote_filename,
)

ALL = ("csv", "geojson", "json", "parquet", "geotiff")


def resolve(**over):
    kwargs = dict(declared=None, final_url="https://p.example/d", headers={}, head=b"", allowed=ALL)
    kwargs.update(over)
    return resolve_format(**kwargs)


class TestTheLadderInOrder:
    def test_1_what_we_asked_for_beats_everything(self):
        """Highest trust because we ASKED: the provider put the format in the
        URL. A server's content type is only what it chose to claim."""
        fmt, _ = resolve(
            declared="geojson",
            final_url="https://p.example/thing.csv",
            headers={"Content-Type": "text/csv"},
            head=b"PAR1",
        )
        assert fmt == "geojson"

    def test_2_the_final_url_suffix(self):
        fmt, name = resolve(final_url="https://p.example/roads.geojson")
        assert (fmt, name) == ("geojson", "roads.geojson")

    def test_3_the_content_disposition_filename(self):
        fmt, name = resolve(
            final_url="https://p.example/download?id=7",
            headers={"Content-Disposition": 'attachment; filename="Bike Routes.csv"'},
        )
        assert fmt == "csv"
        assert name == "Bike_Routes.csv"

    @pytest.mark.parametrize(
        "content_type,expected",
        [
            ("text/csv", "csv"),
            ("application/geo+json", "geojson"),
            ("application/json", "json"),
            ("image/tiff", "geotiff"),
            ("application/vnd.apache.parquet", "parquet"),
            ("text/csv; charset=utf-8", "csv"),
        ],
    )
    def test_4_the_content_type(self, content_type, expected):
        fmt, _ = resolve(headers={"Content-Type": content_type})
        assert fmt == expected

    @pytest.mark.parametrize(
        "head,expected",
        [
            (b"PAR1\x00\x00", "parquet"),
            (b"II*\x00rest", "geotiff"),
            (b"MM\x00*rest", "geotiff"),
            (b"II+\x00rest", "geotiff"),
            (b"MM\x00+rest", "geotiff"),
            (b'{"type": "FeatureCollection", "features": []}', "geojson"),
            (b'  \n{"type":"Feature","geometry":{}}', "geojson"),
            (b'{"results": [1,2,3]}', "json"),
            (b"[1, 2, 3]", "json"),
        ],
    )
    def test_5_the_first_bytes(self, head, expected):
        fmt, _ = resolve(head=head)
        assert fmt == expected

    def test_geojson_is_told_apart_from_json_by_content(self):
        """They are the same media type and often the same extension, so the
        only thing that separates them is what is inside."""
        assert resolve(head=b'{"type":"FeatureCollection","features":[]}')[0] == "geojson"
        assert resolve(head=b'{"type":"something else"}')[0] == "json"
        assert resolve(head=b'{"rows":[]}')[0] == "json"


class TestRefusals:
    # These two asserted that every archive is refused, zip and gzip included.
    # Curio now unpacks those (TestArchives below), so they assert the refusal
    # of the archives it does not unpack, by content type and by name alone.
    @pytest.mark.parametrize(
        "content_type",
        ["application/x-tar", "application/x-7z-compressed", "application/x-bzip2",
         "application/vnd.rar"],
    )
    def test_an_archive_content_type_curio_does_not_unpack_is_refused(self, content_type):
        from utk_curio.backend.app.discovery.domain.formats import refuse_archives

        with pytest.raises(UnsupportedFormatError, match="does not unpack"):
            refuse_archives(content_type, None)
        with pytest.raises(UnsupportedFormatError, match="does not unpack"):
            resolve(headers={"Content-Type": content_type})

    @pytest.mark.parametrize("name", ["bundle.tar.gz", "x.7z", "y.rar", "z.tgz", "w.tar", "v.bz2"])
    def test_an_archive_filename_curio_does_not_unpack_is_refused_too(self, name):
        with pytest.raises(UnsupportedFormatError, match="does not unpack"):
            resolve(final_url=f"https://p.example/{name}")

    def test_something_unidentifiable_says_so_rather_than_guessing(self):
        with pytest.raises(UnsupportedFormatError, match="could not tell"):
            resolve(headers={"Content-Type": "application/octet-stream"}, head=b"\x00\x01\x02")

    def test_a_format_the_source_does_not_offer_names_what_it_does(self):
        with pytest.raises(UnsupportedFormatError, match="offers csv"):
            resolve(final_url="https://p.example/a.geojson", allowed=("csv",))


class TestArchives:
    @pytest.mark.parametrize(
        "content_type,name,head,kind",
        [
            ("application/zip", None, b"", "zip"),
            ("application/x-zip-compressed", None, b"", "zip"),
            ("application/gzip", None, b"", "gzip"),
            ("application/x-gzip; charset=binary", None, b"", "gzip"),
            ("", "tl_2022_17_tabblock20.zip", b"", "zip"),
            ("", "il_wac_S000_JT00_2022.CSV.GZ", b"", "gzip"),
            # Served with nothing to go by: the first bytes decide.
            ("application/octet-stream", None, b"PK\x03\x04rest", "zip"),
            ("application/octet-stream", None, b"\x1f\x8b\x08rest", "gzip"),
            ("application/octet-stream", None, b"7z\xbc\xaf'\x1c\x00\x04", "7z"),
            ("application/octet-stream", None, b"Rar!\x1a\x07\x00", "rar"),
            # A .tar.gz is a tar, whatever its last suffix says.
            ("application/gzip", "bundle.tar.gz", b"", "tar"),
            ("text/csv", "crimes.csv", b"id,date\n", None),
            ("application/octet-stream", None, b"BZh91AY&SY\x00", "bz2"),
            ("application/octet-stream", None, b"\x00" * 257 + b"ustar\x0000", "tar"),
            # Text that only starts like one is text.
            ("text/csv", "crimes.csv", b"BZh,count\n1,2\n", None),
            ("text/csv", "crimes.csv", b"m" * 256 + b"Mustard,1\n", None),
        ],
    )
    def test_what_kind_of_archive_it_is(self, content_type, name, head, kind):
        from utk_curio.backend.app.discovery.domain.formats import archive_kind

        assert archive_kind(content_type, name, head) == kind

    @pytest.mark.parametrize(
        "content_type,name",
        [("application/zip", None), ("application/gzip", None), ("", "data.zip"),
         ("", "wac.csv.gz")],
    )
    def test_zip_and_gzip_are_not_refused(self, content_type, name):
        """Curio unpacks them, so nothing refuses them up front."""
        from utk_curio.backend.app.discovery.domain.formats import refuse_archives

        refuse_archives(content_type, name)


class TestTheFilename:
    def test_the_name_always_agrees_with_the_verdict(self):
        """The installer keys the stored file's suffix off this name and the
        loader keys off the format; disagreeing would generate a loader for a
        file that is not there."""
        fmt, name = resolve(
            declared="geojson", final_url="https://p.example/thing.csv"
        )
        assert fmt == "geojson" and name.endswith(".geojson")

    def test_a_nameless_url_still_gets_one(self):
        fmt, name = resolve(headers={"Content-Type": "text/csv"})
        assert name.endswith(".csv") and len(name) > 4

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../etc/passwd.csv",
            "..\\..\\windows\\system32\\a.csv",
            "/absolute/path.csv",
            "....//....//x.csv",
            "a\x00b.csv",
        ],
    )
    def test_a_hostile_remote_filename_is_flattened(self, hostile):
        """A Content-Disposition filename is attacker-controlled. This is the
        sanitiser; the structural defence is that the dataset DIRECTORY is
        minted as imported.x<uuid> by the installer, which no remote input can
        influence at all."""
        name = safe_remote_filename(hostile, fallback="download.csv")
        assert "/" not in name and "\\" not in name and ".." not in name
        assert "\x00" not in name

    def test_an_empty_or_dotfile_name_falls_back(self):
        assert safe_remote_filename("", fallback="download.csv") == "download.csv"
        assert safe_remote_filename("...", fallback="download.csv") == "download.csv"
        assert safe_remote_filename(None, fallback="download.csv") == "download.csv"

    def test_a_very_long_name_is_bounded(self):
        name = safe_remote_filename("a" * 900 + ".csv", fallback="download.csv")
        assert len(name) <= 120
