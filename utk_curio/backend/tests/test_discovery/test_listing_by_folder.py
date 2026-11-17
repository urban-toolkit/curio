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

    A page holds up to ``max-keys`` entries in key order, or *page_size*
    when it is fewer: S3 may answer fewer, never more. With a delimiter,
    a key with one after the prefix is listed once as its folder, a common
    prefix. A page that leaves entries says so and gives a token, the last
    entry it holds, which the next page starts after. Every URL asked is kept
    in ``calls``, from any thread.
    """

    def __init__(self, base: str, keys: list[str], *, page_size: int | None = None):
        self.base = base
        self.keys = sorted(keys)
        self.page_size = page_size
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
        if self.page_size is not None:
            limit = min(limit, self.page_size)
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

#: July's snapshots of every crossing, a row of :func:`by_month`'s source.
JULY_SNAPSHOTS = "snapshots@month=2025-07-01T00:00:00"


def by_month(manifest):
    """SAGE-IDOT with a row of each month's snapshots, every crossing's
    together: a row whose files are in a folder of each crossing."""
    snapshots = next(spec for spec in manifest.resources if spec.id == "snapshots")
    monthly = dataclasses.replace(snapshots, datasets="per:month", split_by=("month",))
    return dataclasses.replace(manifest, resources=(monthly,))


def few_crossings(*crossings: str) -> list[str]:
    """A bucket of IDOT's layout with one July snapshot and one July file of
    detections for each of *crossings*."""
    start = MONTHS["2025_07"]
    return [
        key
        for crossing in crossings
        for key in (f"{crossing}/images/2025_07/{start}-snapshot.jpg", f"{crossing}/data/{crossing}_2025_07.jsonl")
    ]


def an_add(provider):
    """The storage add path over *provider*. It installs nothing: each add
    here is refused once its scan ends."""
    from utk_curio.backend.app.discovery.application.storage_acquire import StorageAcquire

    def installs(*_args, **_kwargs):
        raise AssertionError("the add went on to install files it should have refused")

    return StorageAcquire(
        user_key="guest", storage_for=lambda _manifest: provider,
        install_path=installs, import_layers=installs, find_held=lambda *_args: None,
    )


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

    def test_a_row_in_more_folders_than_a_scan_lists_is_refused_for_its_folders(self, idot, monkeypatch):
        """The add says what it met: folders, at their bound, not files."""
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        manifest, bucket, _provider = idot
        monthly = by_month(manifest)
        # July's snapshots are in W042's July folder and W065's: two, past a bound of one.
        monkeypatch.setattr(scan, "MAX_FOLDERS", 1)
        with pytest.raises(DownloadTooLarge) as refused:
            an_add(S3Storage(monthly, bucket)).acquire(monthly, JULY_SNAPSHOTS)

        assert str(refused.value) == (
            "Crossing snapshots is in more than 1 folder, the most SAGE-IDOT rail crossings reads at once; "
            "add part of it"
        )

    def test_a_row_in_as_many_folders_as_a_scan_lists_is_listed_whole(self, idot, monkeypatch):
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.providers.s3 import S3Storage

        manifest, bucket, _provider = idot
        monthly = by_month(manifest)
        monkeypatch.setattr(scan, "MAX_FOLDERS", 2)
        add = scan.scan(monthly, S3Storage(monthly, bucket), selection=a_row(monthly, JULY_SNAPSHOTS))

        assert not add.truncated
        assert [len(group.files) for group in add.groups] == [len(CROSSINGS) * SNAPSHOTS]

    def test_a_row_whose_folder_lists_past_its_pages_is_refused_for_them(self, monkeypatch):
        """Its add says the folder's listing ran past its pages, not that no
        file matches the row."""
        from utk_curio.backend.app.discovery.domain.errors import DownloadTooLarge
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
        from utk_curio.backend.app.discovery.providers import s3

        manifest = load_source_manifest(IDOT)
        # 1,000 notes come before the snapshots in W042's July folder: its
        # first page, and the bound is one.
        notes = [f"W042/images/2025_07/0{n:03d}-notes.txt" for n in range(1000)]
        bucket = ListingBucket(BASE, idot_keys() + notes)
        monkeypatch.setattr(s3, "MAX_PAGES", 1)
        with pytest.raises(DownloadTooLarge) as refused:
            an_add(s3.S3Storage(manifest, bucket)).acquire(manifest, month_row("snapshots", "W042", "2025_07"))

        assert str(refused.value) == (
            "Crossing snapshots has a folder whose listing runs past 1 page, "
            "the most SAGE-IDOT rail crossings reads of one folder"
        )


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
                assert rows[month_row("records", crossing, month)] == 1
        assert len(rows) == 4 * len(CROSSINGS) * len(MONTHS)
        assert not result.truncated

    def test_a_bucket_over_the_file_limit_lists_whole_when_each_row_is_under_it(self, idot):
        """The limit holds a row's files: a bucket that grows by a month's
        folder at a time never meets it."""
        from utk_curio.backend.app.discovery.application import scan

        manifest, _bucket, provider = idot
        # Under the bucket's 6,012 matched files, over any one row's 1,500.
        limited = dataclasses.replace(manifest, max_files=2000)
        result = scan.scan(limited, provider)

        assert not result.truncated, "the listing stopped at 2,000 files, though no row holds that many"
        rows = {group.resource_id: len(group.files) for group in result.groups}
        assert all(
            rows.get(month_row("snapshots", crossing, month)) == SNAPSHOTS
            for crossing in CROSSINGS for month in MONTHS
        ), rows
        # A month's file is matched by each of the three resources that read it.
        assert result.matched == len(CROSSINGS) * len(MONTHS) * (SNAPSHOTS + 3)

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
        # bucket's 6,012 matched files over a bound of 4,000.
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

        # A bucket of exactly the bound is listed whole: a month's file is
        # matched by each of the three resources that read it.
        total = len(CROSSINGS) * len(MONTHS) * (SNAPSHOTS + 3)
        monkeypatch.setattr(scan, "MAX_LISTING_FILES", total)
        whole = scan.scan(limited, provider)
        assert whole.matched == total and not whole.truncated, (whole.matched, whole.truncated)


class TestAListingPastItsPages:
    """A bucket lists one folder in up to ``MAX_PAGES`` pages: a listing that
    stops there says it was cut short, as it does at the other bounds."""

    def test_a_folder_of_files_past_its_pages_cuts_the_listing_short(self, idot, monkeypatch):
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.providers import s3

        manifest, bucket, provider = idot
        # A month's 1,500 snapshots are two pages, one past a bound of one.
        monkeypatch.setattr(s3, "MAX_PAGES", 1)
        result = scan.scan(manifest, provider)

        assert bucket.asked()[("W042/images/2025_07/", None)] == 1
        rows = {group.resource_id: len(group.files) for group in result.groups}
        assert rows[month_row("snapshots", "W042", "2025_07")] == 1000, rows
        assert result.truncated, (
            "each month's folder was listed to its first page of two, and the listing did not say it was cut short"
        )

    def test_a_folder_of_files_as_long_as_its_pages_is_listed_whole(self, idot, monkeypatch):
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.providers import s3

        manifest, _bucket, provider = idot
        monkeypatch.setattr(s3, "MAX_PAGES", 2)
        result = scan.scan(manifest, provider)

        rows = {group.resource_id: len(group.files) for group in result.groups}
        assert all(
            rows[month_row("snapshots", crossing, month)] == SNAPSHOTS for crossing in CROSSINGS for month in MONTHS
        ), rows
        assert not result.truncated

    def test_a_list_of_folders_past_its_pages_cuts_the_listing_short(self, monkeypatch):
        """The folders under a prefix come in pages too."""
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
        from utk_curio.backend.app.discovery.providers import s3

        manifest = load_source_manifest(IDOT)
        # Three crossings at two folders a page: two pages, one past a bound of one.
        bucket = ListingBucket(BASE, few_crossings("W042", "W065", "W06E"), page_size=2)
        monkeypatch.setattr(s3, "MAX_PAGES", 1)
        result = scan.scan(manifest, s3.S3Storage(manifest, bucket))

        assert bucket.asked()[("", "/")] == 1
        assert {group.key[0] for group in result.groups} == {"W042", "W065"}
        assert result.truncated, (
            "the bucket's crossings were listed to their first page of two, and the listing did not say it was cut short"
        )

    def test_a_list_of_folders_as_long_as_its_pages_is_listed_whole(self, monkeypatch):
        from utk_curio.backend.app.discovery.application import scan
        from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
        from utk_curio.backend.app.discovery.providers import s3

        manifest = load_source_manifest(IDOT)
        bucket = ListingBucket(BASE, few_crossings("W042", "W065", "W06E"), page_size=2)
        monkeypatch.setattr(s3, "MAX_PAGES", 2)
        result = scan.scan(manifest, s3.S3Storage(manifest, bucket))

        assert {group.key[0] for group in result.groups} == {"W042", "W065", "W06E"}
        assert not result.truncated


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
        assert len(result.groups) == 4 * len(CROSSINGS) * len(MONTHS)


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
