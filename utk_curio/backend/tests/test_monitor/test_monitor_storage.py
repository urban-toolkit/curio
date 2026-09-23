"""The storage walk: its cache, its caps, and its refusal to leak a store name.

The cache is the load-bearing part. Without it a page polling every few seconds
would re-walk the whole state tree on every request, on a public route, which
is a denial of service anybody could trigger with a browser tab.
"""

import os

from utk_curio.backend.app.monitor import storage


class TestCache:
    def test_repeated_requests_inside_the_ttl_walk_once(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(storage, "_walk_everything",
                            lambda: calls.append(1) or _fake_walk())

        for _ in range(12):
            assert client.get("/api/monitor/storage").status_code == 200

        assert len(calls) == 1, "the walk ran more than once inside its TTL"

    def test_the_walk_reruns_once_the_ttl_expires(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(storage, "_walk_everything",
                            lambda: calls.append(1) or _fake_walk())

        clock = [1000.0]
        monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])

        client.get("/api/monitor/storage")
        clock[0] += storage.TTL_SECONDS + 1
        client.get("/api/monitor/storage")

        assert len(calls) == 2

    def test_the_response_reports_its_own_staleness(self, client, monkeypatch):
        monkeypatch.setattr(storage, "_walk_everything", _fake_walk)
        clock = [1000.0]
        monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])

        client.get("/api/monitor/storage")
        clock[0] += 31
        body = client.get("/api/monitor/storage").get_json()

        assert body["ageSeconds"] == 31
        assert body["ttlSeconds"] == storage.TTL_SECONDS


class TestPayload:
    def test_the_documented_shape(self, client):
        body = client.get("/api/monitor/storage").get_json()

        assert isinstance(body["computedAt"], str)
        assert isinstance(body["walkMs"], int)
        assert isinstance(body["truncated"], bool)
        assert set(body["disk"]) == {"totalBytes", "freeBytes"}

        stores = body["userStores"]
        for key in ("count", "totalBytes", "largestBytes", "medianBytes"):
            assert isinstance(stores[key], int), key
        assert len(stores["buckets"]) == 6
        assert stores["buckets"][-1]["leBytes"] is None

    def test_the_breakdown_is_a_fixed_four_row_vocabulary(self, client):
        rows = client.get("/api/monitor/storage").get_json()["breakdown"]
        assert [row["area"] for row in rows] == list(storage.AREAS)

    def test_no_store_name_or_size_vector_reaches_the_payload(self, client,
                                                              state_root):
        """Stores are a histogram, never a list and never a name.

        A sorted size vector would be a per-user row with the label removed:
        anyone holding another ordering of the same users could line them up.
        """
        for name in ("zqxprobe", "alice"):
            store = state_root / "users" / name
            store.mkdir(parents=True)
            (store / "data.bin").write_bytes(b"x" * 2048)
        storage.reset()

        raw = client.get("/api/monitor/storage").get_data(as_text=True)
        assert "zqxprobe" not in raw
        assert "alice" not in raw
        assert "sizesBytes" not in raw

        stores = client.get("/api/monitor/storage").get_json()["userStores"]
        assert stores["count"] == 2


class TestResilience:
    def test_a_missing_area_is_zero_rather_than_an_error(self, client, state_root):
        # No exec-overlays directory exists unless isolation ran. That is the
        # ordinary case on a laptop, not a failure.
        storage.reset()

        body = client.get("/api/monitor/storage").get_json()
        assert body["userStores"]["count"] == 0
        overlays = [r for r in body["breakdown"] if r["area"] == "exec-overlays"][0]
        assert overlays["bytes"] == 0

    def test_an_unreadable_directory_does_not_fail_the_response(self, client,
                                                                state_root):
        locked = state_root / "users" / "locked"
        locked.mkdir(parents=True)
        (locked / "file.bin").write_bytes(b"x" * 10)
        os.chmod(locked, 0o000)
        storage.reset()

        try:
            assert client.get("/api/monitor/storage").status_code == 200
        finally:
            os.chmod(locked, 0o755)

    def test_the_entry_cap_truncates_rather_than_hanging(self, client, state_root,
                                                         monkeypatch):
        store = state_root / "users" / "big"
        store.mkdir(parents=True)
        for i in range(10):
            (store / f"f{i}.bin").write_bytes(b"x")
        monkeypatch.setattr(storage, "MAX_ENTRIES", 2)
        storage.reset()

        body = client.get("/api/monitor/storage").get_json()
        assert body["truncated"] is True


def _fake_walk():
    return {
        "computedAt": "2026-09-22T00:00:00Z",
        "walkMs": 1,
        "truncated": False,
        "userStores": storage._summarise_stores([]),
        "breakdown": [{"area": a, "bytes": 0, "files": 0} for a in storage.AREAS],
        "disk": {"totalBytes": 1, "freeBytes": 1},
    }
