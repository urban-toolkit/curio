"""A file the person downloaded themselves keeps where it came from.

The Dataset Finder's Import states the row's link, or its Data Lake
coordinate. The server records it with when the file arrived and a digest of
its bytes, and marks it as downloaded by hand, so the dataset's page can say
where it came from, and the same file is not registered twice.
"""

from __future__ import annotations

import hashlib
import io
import json

BODY = b"city,count\nChicago,3\nEvanston,1\n"
LINK = "https://data.example.org/cities.csv"


def _import(client, token, body=BODY, lake_source=None, name="cities.csv"):
    data = {"file": (io.BytesIO(body), name)}
    if lake_source is not None:
        data["lakeSource"] = json.dumps(lake_source)
    return client.post("/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
                       data=data, content_type="multipart/form-data")


class TestTheOriginIsRecorded:
    def test_a_link_is_recorded_as_a_hand_download(self, client, user_and_token):
        _user, token = user_and_token
        res = _import(client, token, lake_source={"resourceUrl": LINK})
        assert res.status_code == 201
        lake = res.get_json()["lakeSource"]
        assert lake["resourceUrl"] == LINK and lake["manual"] is True
        assert lake["contentSha256"] == hashlib.sha256(BODY).hexdigest()
        assert lake["fetchedAt"]

    def test_the_server_computes_the_digest_whatever_the_client_says(self, client, user_and_token):
        _user, token = user_and_token
        res = _import(client, token, lake_source={"resourceUrl": LINK, "contentSha256": "0" * 64})
        assert res.get_json()["lakeSource"]["contentSha256"] == hashlib.sha256(BODY).hexdigest()

    def test_a_link_that_is_not_http_is_no_origin(self, client, user_and_token):
        _user, token = user_and_token
        res = _import(client, token, lake_source={"resourceUrl": "javascript:alert(1)"})
        assert res.status_code == 201
        assert res.get_json().get("lakeSource") is None

    def test_an_unreadable_origin_does_not_fail_the_import(self, client, user_and_token):
        _user, token = user_and_token
        res = client.post(
            "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(BODY), "cities.csv"), "lakeSource": "{not json"},
            content_type="multipart/form-data",
        )
        assert res.status_code == 201 and res.get_json().get("lakeSource") is None


class TestTheSameFileIsNotRegisteredTwice:
    def test_the_same_bytes_from_a_remote_origin_answer_with_the_first(self, client, user_and_token):
        _user, token = user_and_token
        first = _import(client, token, lake_source={"resourceUrl": LINK}).get_json()
        again = _import(client, token, lake_source={"resourceUrl": "https://mirror.example.org/c.csv"})
        assert again.status_code == 200
        assert again.get_json()["alreadyPresent"] is True
        assert again.get_json()["id"] == first["id"]

    def test_a_plain_upload_is_unchanged(self, client, user_and_token):
        _user, token = user_and_token
        first = _import(client, token).get_json()
        again = _import(client, token)
        assert again.status_code == 201
        assert again.get_json()["id"] != first["id"]
