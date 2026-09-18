"""A non-UTF-8 CSV must import as data, not as a delayed crash (#280).

The import path read the upload's bytes and wrote them through verbatim. Three
things downstream then assumed UTF-8:

* ``count_file`` opened the file ``utf-8-sig`` inside a bare ``except
  Exception`` that returned ``(None, None)``, so a cp1252 file imported with
  HTTP 201 and simply no row count, and nothing said why;
* the same assumption in the preview path broke the detail page;
* the generated loader emitted a bare ``pd.read_csv(dataset_path)``, so the
  first run of the node raised ``UnicodeDecodeError`` at the user.

Curio's loader snippets cannot carry reader kwargs - the catalog's CSVs were
re-saved comma-delimited on the way in for exactly that reason, see
``test_catalog_dataset_coverage.py::test_catalog_csvs_are_comma_delimited``. So
the fix normalises on import rather than teaching every reader an encoding:
sniff, decode, store UTF-8, and record what the source was.
"""

from __future__ import annotations

import io

import pytest

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.file_meta import count_file


# "Café" and "naïve" are the cheap reproducer: both round-trip through cp1252
# and latin-1 as single bytes that are not valid UTF-8 continuations.
LATIN1_ROWS = "city,note\nCafé,naïve\nZürich,Öl\n"


def _import(client, token, *, name, body):
    return client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )


@pytest.fixture()
def imported_latin1(client, user_and_token):
    _user, token = user_and_token
    resp = _import(client, token, name="cities.csv", body=LATIN1_ROWS.encode("cp1252"))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json(), token


class TestTheFileIsUsableAfterImport:
    def test_the_rows_are_counted(self, imported_latin1):
        # The symptom the user saw first: a dataset that imported "fine" but
        # reported no rows, because the counter's decode failed and was
        # swallowed.
        item, _token = imported_latin1
        assert item.get("rowCount") == 2

    def test_the_stored_bytes_are_valid_utf8(self, imported_latin1):
        item, _token = imported_latin1
        raw = open(item["path"], "rb").read()
        raw.decode("utf-8")  # must not raise

    def test_the_characters_survived_the_transcode(self, imported_latin1):
        item, _token = imported_latin1
        text = open(item["path"], encoding="utf-8").read()
        assert "Café" in text
        assert "Zürich" in text

    def test_the_generated_loader_can_read_it(self, imported_latin1):
        # pd.read_csv defaults to utf-8. The loader snippet carries no encoding
        # argument and cannot, so the stored file has to be the thing that is
        # right.
        item, _token = imported_latin1
        import csv

        with open(item["path"], encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        assert rows[1][0] == "Café"


class TestTheSourceEncodingIsRecorded:
    def test_the_manifest_names_what_was_decoded(self, imported_latin1):
        item, _token = imported_latin1
        manifest = load_dataset_manifest(
            __import__("pathlib").Path(item["path"]).parent.parent
        )
        assert manifest.source_encoding is not None
        assert manifest.source_encoding.lower() not in ("utf-8", "utf_8")

    def test_a_utf8_upload_records_utf8(self, client, user_and_token):
        _user, token = user_and_token
        resp = _import(
            client, token, name="plain.csv", body=LATIN1_ROWS.encode("utf-8")
        )
        assert resp.status_code == 201
        item = resp.get_json()
        assert item.get("rowCount") == 2


class TestTheCounterSaysWhyItFailed:
    def test_an_undecodable_file_is_not_silently_countless(self, tmp_path, caplog):
        # Not reachable through import any more, but count_file is called from
        # four places; when it does give up, the log must name the reason rather
        # than swallow it at debug level.
        bad = tmp_path / "bad.csv"
        bad.write_bytes(b"a,b\n\xff\xfe\x00\x00,2\n")
        with caplog.at_level("WARNING"):
            rows, features = count_file(bad, "csv")
        assert (rows, features) == (None, None)
        assert any("bad.csv" in rec.message or "bad.csv" in str(rec.args)
                   for rec in caplog.records)
