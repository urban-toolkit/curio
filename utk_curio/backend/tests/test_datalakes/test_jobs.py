"""The download job store.

Three of these pin things ``streetvision/jobs.py`` - the store this one is
modelled on - does not do: jobs are per user, they can be cancelled, and
finished ones are swept. The isolation one matters most: that store's
``get_job(job_id)`` returns anyone's job to anyone who guesses an id.
"""

from __future__ import annotations

import time

import pytest

from utk_curio.backend.app.datalakes.application import jobs as J


@pytest.fixture()
def store():
    return J.JobStore(ttl_seconds=1000)


class TestIsolation:
    def test_a_job_is_readable_by_its_owner(self, store):
        job = store.create("alice", "lake.a.b@1", "r1")
        assert store.get("alice", job.job_id) is job

    def test_another_user_cannot_read_it_even_with_the_id(self, store):
        """The gap in the store this is modelled on. Keyed by the pair, so
        asking for someone else's id is indistinguishable from asking for one
        that does not exist - which is the right answer to both."""
        job = store.create("alice", "lake.a.b@1", "r1")
        assert store.get("bob", job.job_id) is None

    def test_another_user_cannot_cancel_it(self, store):
        job = store.create("alice", "lake.a.b@1", "r1")
        assert store.cancel("bob", job.job_id) is False
        assert job.cancelled is False

    def test_two_users_can_hold_jobs_at_once(self, store):
        a = store.create("alice", "lake.a.b@1", "r1")
        b = store.create("bob", "lake.a.b@1", "r1")
        assert a.job_id != b.job_id
        assert store.get("alice", a.job_id) and store.get("bob", b.job_id)


class TestLifecycle:
    def test_a_new_job_is_queued(self, store):
        job = store.create("alice", "lake.a.b@1", "r1")
        assert job.status == "queued"
        assert job.to_row()["status"] == "queued"

    def test_finishing_sets_the_status_and_the_fields(self, store):
        job = store.create("alice", "lake.a.b@1", "r1")
        store.finish(job, "completed", dataset_id="imported.x1", stage_message="Done")
        assert job.status == "completed"
        assert job.to_row()["datasetId"] == "imported.x1"

    def test_cancelling_flags_it_rather_than_killing_it(self, store):
        """Checked between chunks, so it takes effect on the next one. There is
        no safe way to interrupt a write mid-chunk."""
        job = store.create("alice", "lake.a.b@1", "r1")
        assert store.cancel("alice", job.job_id) is True
        assert job.cancelled is True
        assert job.status != "cancelled", "the worker sets the terminal state"

    @pytest.mark.parametrize("terminal", sorted(J.TERMINAL))
    def test_a_finished_job_cannot_be_cancelled(self, store, terminal):
        job = store.create("alice", "lake.a.b@1", "r1")
        store.finish(job, terminal)
        assert store.cancel("alice", job.job_id) is False

    def test_the_row_carries_what_a_progress_bar_needs(self, store):
        job = store.create("alice", "lake.a.b@1", "r1")
        job.bytes_read, job.total_bytes = 512, 2048
        row = job.to_row()
        assert row["bytesRead"] == 512 and row["totalBytes"] == 2048
        assert set(row) >= {"jobId", "status", "stageMessage", "error", "sourceId"}

    def test_total_bytes_may_be_unknown(self, store):
        """A portal need not send Content-Length, and the bar is indeterminate
        when it does not."""
        job = store.create("alice", "lake.a.b@1", "r1")
        assert job.to_row()["totalBytes"] is None


class TestTheSweep:
    def test_a_finished_job_is_dropped_after_its_ttl(self, monkeypatch):
        store = J.JobStore(ttl_seconds=10)
        job = store.create("alice", "lake.a.b@1", "r1")
        store.finish(job, "completed")
        assert store.get("alice", job.job_id) is not None
        monkeypatch.setattr(J.time, "monotonic", lambda: job.finished_at + 11)
        assert store.get("alice", job.job_id) is None

    def test_an_unfinished_job_is_never_swept(self, monkeypatch):
        """However long it takes. A slow portal is not a reason to forget a
        download that is still running."""
        store = J.JobStore(ttl_seconds=1)
        job = store.create("alice", "lake.a.b@1", "r1")
        monkeypatch.setattr(J.time, "monotonic", lambda: 10 ** 9)
        assert store.get("alice", job.job_id) is job


class TestConcurrencyCap:
    def test_a_user_may_hold_only_so_many_at_once(self):
        from utk_curio.backend.app.datalakes.domain.errors import RateLimited
        from utk_curio.backend.app.datalakes.infrastructure.ratelimit import DownloadSlots

        slots = DownloadSlots(limit=2)
        slots.acquire("alice")
        slots.acquire("alice")
        with pytest.raises(RateLimited, match="already have"):
            slots.acquire("alice")

    def test_finishing_one_frees_a_slot(self):
        from utk_curio.backend.app.datalakes.infrastructure.ratelimit import DownloadSlots

        slots = DownloadSlots(limit=1)
        slots.acquire("alice")
        slots.release("alice")
        slots.acquire("alice")  # no raise

    def test_one_users_downloads_do_not_block_another(self):
        from utk_curio.backend.app.datalakes.infrastructure.ratelimit import DownloadSlots

        slots = DownloadSlots(limit=1)
        slots.acquire("alice")
        slots.acquire("bob")  # no raise


class TestTheWorkerDoesNotShareTheRequestsSession:
    """A ``User`` row belongs to the session that loaded it.

    Handing the request's instance to the download thread puts two threads on
    one session and one connection, and reading any attribute off it there can
    emit a query. The loser of that race gets a decode failure from SQLAlchemy
    ("tuple index out of range"), which surfaces as a 500 on whatever request
    was in flight - in CI, on the job poll's auth check, with a traceback
    naming ``get_current_user`` and nothing pointing at the download.

    It needs the poll and the worker to overlap, so it is intermittent: it
    passed locally and in one CI run before failing in the next, on a commit
    that touched none of this.
    """

    def test_the_worker_loads_its_own_user(
        self, app, user_and_token, shipped_root, fixture_corpus, monkeypatch
    ):
        from utk_curio.backend.app.datalakes import service as service_mod

        seen: dict = {}
        real = service_mod.LakeAcquire.acquire

        def _spy(self, *a, **k):
            seen["worker_user"] = self.user
            return real(self, *a, **k)

        monkeypatch.setattr(service_mod.LakeAcquire, "acquire", _spy)

        user, _token = user_and_token
        with app.app_context():
            from utk_curio.backend.app.users import repositories as user_repo

            request_user = user_repo.user_by_id(user.id)
            svc = service_mod.DataLakeService(str(user.id), user=request_user)
            try:
                svc.start_acquire(
                    "lake.cityofchicago.data-portal@1", "ijzp-q8t2", fmt="csv"
                )
            except Exception:  # noqa: BLE001 - the download itself is not the point
                pass
            deadline = time.time() + 5
            while "worker_user" not in seen and time.time() < deadline:
                time.sleep(0.01)

        assert "worker_user" in seen, "the worker never ran"
        assert seen["worker_user"] is not None
        assert seen["worker_user"] is not request_user, (
            "the worker is using the request thread's User instance - two "
            "threads, one session, one connection"
        )
