"""A bucket whose paths start with a field, listed by the folders its rows need.

Every path of SAGE-IDOT starts with its crossing, ``{crossing}/images/{month}/``
and ``{crossing}/data/``, so no name narrows where its files are. Its listing
and each add once paged through the whole bucket from its first key: 169
pages, about 90 s from outside utk, for a month of one crossing.

Here the shipped source reads a bucket of IDOT's shape, smaller, through the
real S3 provider. The bucket is held in memory by a transport that answers
ListObjectsV2 as S3 does (up to 1000 entries a page in key order, a
continuation token, and with a delimiter each folder once) and keeps every URL
it was asked. No socket opens.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from xml.sax.saxutils import escape

import pytest

REPO = Path(__file__).resolve().parents[4]
IDOT = REPO / "discovery" / "source.sage.idot-crossings@1"
BASE = "https://data.urbantk.org/idot"

CROSSINGS = ("W042", "W065")
#: Each month's folder, and its first snapshot's time in ns since 1970.
MONTHS = {"2025_07": 1_751_328_000 * 10**9, "2025_08": 1_754_006_400 * 10**9}
#: Snapshots in each month's folder: two listing pages.
SNAPSHOTS = 1500
FIVE_MINUTES_NS = 300 * 10**9


def idot_keys() -> list[str]:
    """IDOT's layout: each crossing's snapshots by month and its monthly
    detections, and a ``sample/`` folder that no resource names."""
    keys = []
    for crossing in CROSSINGS:
        for month, start in MONTHS.items():
            keys += [f"{crossing}/images/{month}/{start + n * FIVE_MINUTES_NS}-snapshot.jpg" for n in range(SNAPSHOTS)]
            keys.append(f"{crossing}/data/{crossing}_{month}.jsonl")
        keys.append(f"sample/{crossing}/detections.jsonl")
        keys += [f"sample/{crossing}/{n}.jpg" for n in range(3)]
    return keys


class ListingBucket:
    """An S3 endpoint over *keys*, answering ListObjectsV2 as S3 does.

    A page holds up to ``max-keys`` entries in key order. With a delimiter,
    a key with one after the prefix is listed once as its folder, a common
    prefix. A page that leaves entries says so and gives a token, the last
    entry it holds, which the next page starts after. Every URL asked is kept
    in ``calls``, from any thread.
    """

    def __init__(self, base: str, keys: list[str]):
        self.base = base
        self.keys = sorted(keys)
        self.calls: list[str] = []

    def json_get(self, url, *, credential=None, headers=None):
        self.calls.append(url)
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{self.base}/", url
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        assert query.get("list-type") == "2", url
        prefix, delimiter = query.get("prefix", ""), query.get("delimiter")
        after = query.get("continuation-token")
        entries: list[tuple[str, str]] = []
        for key in self.keys:
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix):]
            if delimiter and delimiter in rest:
                folder = prefix + rest.split(delimiter, 1)[0] + delimiter
                if not entries or entries[-1] != ("folder", folder):
                    entries.append(("folder", folder))
            else:
                entries.append(("key", key))
        if after is not None:
            entries = [entry for entry in entries if entry[1] > after]
        limit = int(query.get("max-keys", "1000"))
        page, left = entries[:limit], entries[limit:]
        body = "".join(
            f"<Contents><Key>{escape(name)}</Key><Size>1000</Size>"
            f"<LastModified>2025-10-21T00:00:00.000Z</LastModified><ETag>\"e{len(name)}\"</ETag></Contents>"
            if kind == "key" else f"<CommonPrefixes><Prefix>{escape(name)}</Prefix></CommonPrefixes>"
            for kind, name in page
        )
        token = f"<NextContinuationToken>{escape(page[-1][1])}</NextContinuationToken>" if left else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Prefix>{escape(prefix)}</Prefix><KeyCount>{len(page)}</KeyCount>"
            f"<IsTruncated>{'true' if left else 'false'}</IsTruncated>{token}{body}</ListBucketResult>"
        )

    def asked(self) -> Counter:
        """Each listing asked for, as ``(prefix, delimiter)``, with its pages."""
        out: Counter = Counter()
        for url in self.calls:
            query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
            out[(query.get("prefix", ""), query.get("delimiter"))] += 1
        return out


@pytest.fixture()
def idot():
    """The shipped SAGE-IDOT source, and its S3 provider over the bucket."""
    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
    from utk_curio.backend.app.discovery.providers.s3 import S3Storage

    manifest = load_source_manifest(IDOT)
    bucket = ListingBucket(BASE, idot_keys())
    return manifest, bucket, S3Storage(manifest, bucket)


def a_row(manifest, resource_id):
    from utk_curio.backend.app.discovery.application import scan

    return scan.parse_resource_id(manifest, resource_id)


def month_row(resource: str, crossing: str, month: str) -> str:
    return f"{resource}@crossing={crossing};month={month[:4]}-{month[5:]}-01T00:00:00"


#: The whole bucket from its first key, page after page: what main asked.
WHOLE_BUCKET = ("", None)


class TestAnAdd:
    def test_a_months_snapshots_list_only_that_months_folder(self, idot):
        from utk_curio.backend.app.discovery.application import scan

        manifest, bucket, provider = idot
        result = scan.scan(manifest, provider, selection=a_row(manifest, month_row("snapshots", "W042", "2025_07")))

        assert WHOLE_BUCKET not in bucket.asked(), (
            f"the add paged through the whole bucket: {bucket.asked()[WHOLE_BUCKET]} pages"
        )
        # The crossings, then W042's months, then that month's two pages.
        assert bucket.asked() == Counter({
            ("", "/"): 1, ("W042/images/", "/"): 1, ("W042/images/2025_07/", None): 2,
        })
        [group] = result.groups
        assert len(group.files) == SNAPSHOTS and not result.truncated
        assert {f.relpath.rsplit("/", 1)[0] for f in group.files} == {"W042/images/2025_07"}

    def test_a_months_detections_list_only_that_crossings_data_folder(self, idot):
        from utk_curio.backend.app.discovery.application import scan

        manifest, bucket, provider = idot
        result = scan.scan(manifest, provider, selection=a_row(manifest, month_row("detections", "W065", "2025_08")))

        assert WHOLE_BUCKET not in bucket.asked(), (
            f"the add paged through the whole bucket: {bucket.asked()[WHOLE_BUCKET]} pages"
        )
        assert bucket.asked() == Counter({("", "/"): 1, ("W065/data/", None): 1})
        [group] = result.groups
        assert [f.relpath for f in group.files] == ["W065/data/W065_2025_08.jsonl"]


class TestTheListing:
    def test_it_lists_the_folders_its_rows_need_and_no_other_file(self, idot):
        from utk_curio.backend.app.discovery.application import scan

        manifest, bucket, provider = idot
        result = scan.scan(manifest, provider)

        assert WHOLE_BUCKET not in bucket.asked(), (
            f"the listing paged through the whole bucket: {bucket.asked()[WHOLE_BUCKET]} pages"
        )
        # Folders, a level at a time: the crossings (sample/ looks like one),
        # each one's months, then each month's files and each data folder.
        expected = Counter({("", "/"): 1})
        for crossing in (*CROSSINGS, "sample"):
            expected[(f"{crossing}/images/", "/")] = 1
            expected[(f"{crossing}/data/", None)] = 1
        for crossing in CROSSINGS:
            for month in MONTHS:
                expected[(f"{crossing}/images/{month}/", None)] = 2
        assert bucket.asked() == expected
        rows = {group.resource_id: len(group.files) for group in result.groups}
        for crossing in CROSSINGS:
            for month in MONTHS:
                assert rows[month_row("snapshots", crossing, month)] == SNAPSHOTS
                assert rows[month_row("detections", crossing, month)] == 1
                assert rows[month_row("frames", crossing, month)] == 1
        assert len(rows) == 3 * len(CROSSINGS) * len(MONTHS)
        assert not result.truncated

    def test_a_bucket_over_the_file_limit_lists_whole_when_each_row_is_under_it(self, idot):
        """The limit holds a row's files: a bucket that grows by a month's
        folder at a time never meets it."""
        from utk_curio.backend.app.discovery.application import scan

        manifest, _bucket, provider = idot
        # Under the bucket's 6,008 matched files, over any one row's 1,500.
        limited = dataclasses.replace(manifest, max_files=2000)
        result = scan.scan(limited, provider)

        assert not result.truncated, "the listing stopped at 2,000 files, though no row holds that many"
        rows = {group.resource_id: len(group.files) for group in result.groups}
        assert all(
            rows.get(month_row("snapshots", crossing, month)) == SNAPSHOTS
            for crossing in CROSSINGS for month in MONTHS
        ), rows
        assert result.matched == len(CROSSINGS) * len(MONTHS) * (SNAPSHOTS + 2)

    def test_a_row_over_the_file_limit_stops_alone_and_its_add_is_refused(self, idot):
        from utk_curio.backend.app.discovery.application import scan

        manifest, _bucket, provider = idot
        limited = dataclasses.replace(manifest, max_files=1000)
        result = scan.scan(limited, provider)

        assert result.truncated
        rows = {group.resource_id: len(group.files) for group in result.groups}
        for crossing in CROSSINGS:
            for month in MONTHS:
                assert rows[month_row("snapshots", crossing, month)] == 1000
                assert rows[month_row("detections", crossing, month)] == 1
        add = scan.scan(limited, provider, selection=a_row(limited, month_row("snapshots", "W065", "2025_08")))
        assert add.truncated and [len(group.files) for group in add.groups] == [1000]

    def test_a_listing_stops_at_its_bound_of_files_though_each_row_is_under_the_file_limit(self, idot, monkeypatch):
        """A whole listing holds up to ``MAX_LISTING_FILES`` files, its rows'
        together: past them it stops and says it was cut short, though no row
        is full."""
        from utk_curio.backend.app.discovery.application import scan

        manifest, _bucket, provider = idot
        # Each row's 1,500 snapshots under the row limit of 2,000, and the
        # bucket's 6,008 matched files over a bound of 4,000.
        limited = dataclasses.replace(manifest, max_files=2000)
        bound = 4000
        monkeypatch.setattr(scan, "MAX_LISTING_FILES", bound, raising=False)
        result = scan.scan(limited, provider)

        assert result.matched == bound, f"the listing held {result.matched:,} files, past its bound of {bound:,}"
        assert result.truncated, f"the listing stopped at its bound of {bound:,} files and did not say it was cut short"
        rows = {group.resource_id: len(group.files) for group in result.groups}
        assert sum(rows.values()) == bound and max(rows.values()) < limited.max_files, rows
        # The folders are read in key order, so the first crossing's rows are whole.
        assert all(rows[month_row("snapshots", "W042", month)] == SNAPSHOTS for month in MONTHS), rows

        # A bucket of exactly the bound is listed whole.
        total = len(CROSSINGS) * len(MONTHS) * (SNAPSHOTS + 2)
        monkeypatch.setattr(scan, "MAX_LISTING_FILES", total)
        whole = scan.scan(limited, provider)
        assert whole.matched == total and not whole.truncated, (whole.matched, whole.truncated)


class TestWhatIsListedAsBefore:
    def test_a_template_whose_folders_name_no_row_is_listed_under_its_leading_names(self):
        """As SideSeeing's walks: a folder per walk, and one row of them all."""
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest_from_dir
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        manifest = load_source_manifest_from_dir(REPO / "discovery" / "source.sideseeing.street-captures@1")
        walks = [f"chicago/west-loop/2026-10-26-1{n}-03-17-016/{name}"
                 for n in range(4) for name in ("video.mp4", "gps.csv", "metadata.json")]
        bucket = ListingBucket("https://data.urbantk.org/sideseeing", [*walks, "sao-paulo/bras/raw/a.mp4"])

        result = scan.scan(manifest, S3Storage(manifest, bucket))

        assert bucket.asked() == Counter({("chicago/west-loop/", None): 1})
        assert {group.resource_id: len(group.files) for group in result.groups}["walks"] == 4

    def test_a_provider_that_lists_no_folders_lists_the_whole_bucket(self, idot):
        from utk_curio.backend.app.discovery.application import scan

        manifest, bucket, provider = idot

        class FilesOnly:
            """A provider that lists files and no folders, as a folder's or a repository's."""

            type = "s3"
            scan = staticmethod(provider.scan)

        result = scan.scan(manifest, FilesOnly())

        assert bucket.asked() == Counter({WHOLE_BUCKET: 7})
        assert len(result.groups) == 3 * len(CROSSINGS) * len(MONTHS)


class TestTheFolders:
    def test_a_templates_folders_end_at_its_file_name_or_a_double_star(self):
        from utk_curio.backend.app.discovery.domain.templates import compile_template

        snapshots = compile_template("{crossing}/images/{month:%Y_%m}/{ns:int}-snapshot.jpg")
        assert [(f.text, f.literal, [c.name for c in f.captures]) for f in snapshots.folders] == [
            ("{crossing}", False, ["crossing"]), ("images", True, []), ("{month:%Y_%m}", False, ["month"]),
        ]
        assert snapshots.folders[2].match("2025_07") == {"month": datetime(2025, 7, 1)}
        # The whole name or nothing, and a value its type cannot read is no match.
        assert snapshots.folders[2].match("2025_07x") is None and snapshots.folders[2].match("2025_13") is None
        assert [f.text for f in compile_template("survey/{year:int}/**/*").folders] == ["survey", "{year:int}"]

    def test_a_bucket_prefix_ending_partway_through_a_name_names_each_folder_after_it(self):
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest_from_dir
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        idot = load_source_manifest_from_dir(IDOT)
        manifest = dataclasses.replace(idot, provider=dataclasses.replace(idot.provider, options={"prefix": "W0"}))
        # A hidden folder, and one named by the prefix alone, name no folder.
        bucket = ListingBucket(BASE, idot_keys() + ["W0.hidden/x.jpg", "W0/x.jpg"])

        assert S3Storage(manifest, bucket).folders() == ["42", "65"]
        assert bucket.asked() == Counter({("W0", "/"): 1})
