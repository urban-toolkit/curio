"""The format ladder, and the filenames it is handed.

Getting this wrong is not cosmetic: the format decides which loader the Data
Catalog generates, so a GeoJSON filed as ``json`` gives the user a node that
returns a dict where they expected a GeoDataFrame.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datalakes.domain.errors import UnsupportedFormatError
from utk_curio.backend.app.datalakes.domain.formats import (
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
    @pytest.mark.parametrize(
        "content_type",
        ["application/zip", "application/gzip", "application/x-tar", "application/x-7z-compressed"],
    )
    def test_an_archive_content_type_is_refused(self, content_type):
        """Nothing is unpacked: that is the decompression-bomb surface and it
        deserves its own design rather than arriving as a side effect."""
        with pytest.raises(UnsupportedFormatError, match="archive"):
            resolve(headers={"Content-Type": content_type})

    @pytest.mark.parametrize("name", ["data.zip", "bundle.tar.gz", "x.7z", "y.rar"])
    def test_an_archive_filename_is_refused_too(self, name):
        with pytest.raises(UnsupportedFormatError, match="archive"):
            resolve(final_url=f"https://p.example/{name}")

    def test_something_unidentifiable_says_so_rather_than_guessing(self):
        with pytest.raises(UnsupportedFormatError, match="could not tell"):
            resolve(headers={"Content-Type": "application/octet-stream"}, head=b"\x00\x01\x02")

    def test_a_format_the_source_does_not_offer_names_what_it_does(self):
        with pytest.raises(UnsupportedFormatError, match="offers csv"):
            resolve(final_url="https://p.example/a.geojson", allowed=("csv",))


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
