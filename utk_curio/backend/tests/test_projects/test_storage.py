"""Tests for projects/storage.py — FS operations."""
import json
import pytest

from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.schemas import OutputRef


def test_ensure_project_dir(tmp_curio):
    d = storage.ensure_project_dir("1", "proj-aaa")
    assert d.exists()
    assert (d / "data").exists()


def test_write_and_read_spec(tmp_curio):
    spec = {"dataflow": {"name": "test", "nodes": [], "edges": []}}
    storage.write_spec("1", "proj-bbb", spec)
    result = storage.read_spec("1", "proj-bbb")
    assert result == spec


def test_read_spec_missing(tmp_curio):
    assert storage.read_spec("1", "no-exist") is None


def test_copy_outputs_happy(tmp_curio):
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "file1.data").write_bytes(b"hello")

    refs = [OutputRef(node_id="n1", filename="file1.data")]
    copied = storage.copy_outputs("1", "proj-ccc", refs)
    assert len(copied) == 1

    proj_data = storage.project_dir("1", "proj-ccc") / "data" / "file1.data"
    assert proj_data.read_bytes() == b"hello"


def test_copy_outputs_missing_source(tmp_curio):
    refs = [OutputRef(node_id="n1", filename="missing.data")]
    copied = storage.copy_outputs("1", "proj-ddd", refs)
    assert len(copied) == 0


def test_hydrate_outputs(tmp_curio):
    proj_dir = storage.ensure_project_dir("1", "proj-eee")
    (proj_dir / "data" / "out.data").write_bytes(b"world")

    refs = [OutputRef(node_id="n1", filename="out.data")]
    hydrated = storage.hydrate_outputs("1", "proj-eee", refs)
    assert len(hydrated) == 1

    shared = storage._shared_data_dir()
    assert (shared / "out.data").read_bytes() == b"world"


def test_hydrate_outputs_from_user_dataset_store(tmp_curio):
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node

    user_key = "1"
    node_id = "node-hydrate"
    install_computed_file_for_node(
        user_key,
        b"city,count\nChicago,10\n",
        "hydrate_out.csv",
        "csv",
        node_id=node_id,
    )

    spec = {
        "dataflow": {
            "datasets": [{
                "datasetId": "computed.node-hydrate",
                "dirName": "computed.node-hydrate@1",
                "origin": "computed",
                "producerNodeId": node_id,
            }],
        },
    }
    refs = [OutputRef(node_id=node_id, filename="hydrate_out.csv")]
    hydrated = storage.hydrate_outputs("1", "proj-hydrate", refs, spec=spec)
    assert len(hydrated) == 1

    shared = storage._shared_data_dir()
    assert (shared / "hydrate_out.csv").read_text(encoding="utf-8").startswith("city,count")


def test_path_traversal_blocked(tmp_curio):
    with pytest.raises(PermissionError, match="traversal"):
        storage.project_dir("1", "../../etc")


def test_write_and_read_manifest(tmp_curio):
    storage.ensure_project_dir("1", "proj-fff")
    refs = [OutputRef(node_id="n1", filename="x.data")]
    storage.write_manifest("1", "proj-fff", 1, refs)
    m = storage.read_manifest("1", "proj-fff")
    assert m["project_id"] == "proj-fff"
    assert len(m["outputs"]) == 1


def test_delete_tree(tmp_curio):
    d = storage.ensure_project_dir("1", "proj-ggg")
    assert d.exists()
    storage.delete_tree("1", "proj-ggg")
    assert not d.exists()


# ── merge_dataflow_dataset_ref (#144c) ──────────────────────────────────────

def test_merge_dataflow_dataset_ref_missing_project(tmp_curio):
    # No spec on disk → False, and no project dir is created as a side effect.
    assert storage.merge_dataflow_dataset_ref("1", "proj-none", {"datasetId": "x"}) is False
    assert not storage.project_dir("1", "proj-none").exists()


def test_merge_dataflow_dataset_ref_upsert_and_append(tmp_curio):
    storage.write_spec("1", "proj-merge", {"dataflow": {"datasets": []}})

    # Append a new ref.
    assert storage.merge_dataflow_dataset_ref(
        "1", "proj-merge",
        {"datasetId": "computed.a", "producerNodeId": "na", "dirName": "computed.a@1"},
    ) is True
    # Upsert (same datasetId) merges fields rather than duplicating.
    assert storage.merge_dataflow_dataset_ref(
        "1", "proj-merge",
        {"datasetId": "computed.a", "producerNodeId": "na", "publishedToHub": True},
    ) is True

    refs = storage.read_spec("1", "proj-merge")["dataflow"]["datasets"]
    assert len(refs) == 1
    assert refs[0]["dirName"] == "computed.a@1"
    assert refs[0]["publishedToHub"] is True


def test_merge_dataflow_dataset_ref_concurrent_no_lost_update(tmp_curio):
    """Concurrent upserts of distinct refs must all survive (no lost update)."""
    import threading

    storage.write_spec("1", "proj-conc", {"dataflow": {"datasets": []}})

    n = 24
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()  # maximize overlap of the read-modify-write windows
        storage.merge_dataflow_dataset_ref(
            "1", "proj-conc",
            {"datasetId": f"computed.{i}", "producerNodeId": f"n{i}"},
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    refs = storage.read_spec("1", "proj-conc")["dataflow"]["datasets"]
    ids = {r["datasetId"] for r in refs}
    assert ids == {f"computed.{i}" for i in range(n)}


def test_installed_file_for_node_swallows_path_traversal(tmp_curio):
    """A crafted dirName that resolves outside the base must not 500 the load
    (review finding B12) — PathTraversalError is a PermissionError, not ValueError."""
    spec = {"dataflow": {"datasets": [
        {"producerNodeId": "n", "dirName": "../../../../etc/passwd"},
    ]}}
    # Must return None rather than raising PathTraversalError out of load_project.
    assert storage._installed_file_for_node("1", spec, "n") is None


# ---------------------------------------------------------------------------
# persisted_output_refs — #144: manifest must only claim durably-recoverable
# outputs, never ones backed solely by the volatile shared cache.
# ---------------------------------------------------------------------------

def test_persisted_output_refs_excludes_shared_cache_only(tmp_curio):
    """An output present only in the shared scratch cache is NOT durable."""
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "cache_only.data").write_bytes(b"x")

    refs = [OutputRef(node_id="n1", filename="cache_only.data")]
    # No legacy copy, no installed dataset ref in the spec -> dropped.
    kept = storage.persisted_output_refs("1", "proj-cache", refs, spec={"dataflow": {}})
    assert kept == []


def test_persisted_output_refs_keeps_legacy_copy(tmp_curio):
    """An output with a legacy project/data copy survives a reload -> kept."""
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "leg.data").write_bytes(b"x")
    refs = [OutputRef(node_id="n1", filename="leg.data")]
    storage.copy_outputs("1", "proj-legacy", refs)  # writes project/data/leg.data

    kept = storage.persisted_output_refs("1", "proj-legacy", refs, spec={"dataflow": {}})
    assert [r.filename for r in kept] == ["leg.data"]


def test_persisted_output_refs_drops_unsafe_filename_without_raising(tmp_curio):
    """An output filename with a char outside the safe set must be dropped, not
    raise PathTraversalError (a PermissionError the save routes don't catch and
    would surface as a 500)."""
    safe_ref = OutputRef(node_id="ok", filename="good.data")
    # Space is outside [A-Za-z0-9._-] -> validate_component raises; CJK/emoji etc.
    # would trigger the same path.
    unsafe_ref = OutputRef(node_id="bad", filename="bad name.data")
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "good.data").write_bytes(b"x")
    storage.copy_outputs("1", "proj-unsafe", [safe_ref])  # durable legacy copy

    kept = storage.persisted_output_refs(
        "1", "proj-unsafe", [safe_ref, unsafe_ref], spec={"dataflow": {}}
    )
    # No raise; the unsafe ref is simply omitted (never durably persistable).
    assert [r.filename for r in kept] == ["good.data"]


class _FakeMsvcrt:
    LK_LOCK = 1   # blocking acquire
    LK_NBLCK = 2  # non-blocking acquire (must NOT be used — it can't wait)
    LK_UNLCK = 0

    def __init__(self, fail_times: int = 0):
        # Record (mode, nbytes) only for calls that did not raise, so the
        # assertions reflect the lock that was actually taken/released.
        self.calls = []
        self.lock_attempts = 0
        self._fail_remaining = fail_times

    def locking(self, fd, mode, nbytes):
        if mode == self.LK_LOCK:
            self.lock_attempts += 1
            if self._fail_remaining > 0:
                self._fail_remaining -= 1
                # Mirror msvcrt: a contended blocking lock retries internally
                # for ~10s and then raises OSError instead of waiting forever.
                raise OSError("Resource deadlock avoided")
        self.calls.append((mode, nbytes))


def test_spec_write_lock_uses_msvcrt_when_fcntl_absent(tmp_curio, monkeypatch):
    """#144: on Windows (no fcntl) the lock must still take a cross-process
    msvcrt lock, not silently degrade to the in-process layer only."""
    fake = _FakeMsvcrt()
    monkeypatch.setattr(storage, "fcntl", None)
    monkeypatch.setattr(storage, "msvcrt", fake)

    with storage.spec_write_lock("1", "proj-win"):
        pass

    # The blocking mode (not the non-blocking LK_NBLCK) must be used, on a
    # 1-byte region, and the lock must be released.
    assert (fake.LK_LOCK, 1) in fake.calls, "should acquire the cross-process lock"
    assert (fake.LK_UNLCK, 1) in fake.calls, "should release the cross-process lock"
    assert all(mode != fake.LK_NBLCK for mode, _ in fake.calls), (
        "must use the blocking lock so a contended waiter waits, not LK_NBLCK"
    )


def test_spec_write_lock_msvcrt_blocks_through_contention(tmp_curio, monkeypatch):
    """#144(c): the actual race — a contended Windows lock whose LK_LOCK raises
    OSError after its ~10s window — must be retried until the region frees, not
    surfaced as an uncaught OSError (HTTP 500) out of the save."""
    fake = _FakeMsvcrt(fail_times=3)
    monkeypatch.setattr(storage, "fcntl", None)
    monkeypatch.setattr(storage, "msvcrt", fake)

    # Must NOT raise despite three timeouts before the region becomes free.
    with storage.spec_write_lock("1", "proj-win-contended"):
        pass

    assert fake.lock_attempts == 4, "should re-issue the blocking lock until acquired"
    assert (fake.LK_LOCK, 1) in fake.calls
    assert (fake.LK_UNLCK, 1) in fake.calls
