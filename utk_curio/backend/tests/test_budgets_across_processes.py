"""Budgets over what a start's backend processes share keep today's limits
whole across them, rather than one limit in each process.

``curio.py start --backend-processes N`` runs N backends, and a dataflow
belongs to one of them. What a budget limits is shared by all of them: the
sandbox's isolated pool, the machine's package workers, an account, a
visitor's address, a portal, Nominatim. Each process held a budget of its own,
so together they allowed N times the limit.

Each test names a start of two processes, with a state folder of its own. The
other process is a forked child (``_support/two_processes.py``), which names
itself process 1 and takes a share of a budget; this one, process 0, is
refused while that share is held, and a share whose process died, ended as a
crash ends it (``os._exit``), is free again at once. A budget that is spent
rather than held (a rate, a pace, a run of failures) stays spent across them.

With one process every budget is what it was, which its own tests, unchanged,
show; ``TestTheSharedBudgets`` adds that one process keeps no file of them.
"""
from __future__ import annotations

import functools
import os
import stat
import threading
import time

import pytest

from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.discovery.application import places
from utk_curio.backend.app.discovery.domain.errors import RateLimited
from utk_curio.backend.app.discovery.infrastructure import ratelimit
from utk_curio.backend.app.packages.builder import jobs as build_jobs
from utk_curio.backend.app.packages.builder.models import parse_build_request
from utk_curio.backend.app.packages.infrastructure import backend_runtime
from utk_curio.backend.app.runs import jobs, viewer
from utk_curio.backend.tests._support.two_processes import PATIENCE_S, Window, in_another_process, race

#: How long a probe here waits for a place before it counts as refused.
WAIT_S = 0.25
#: An account; its key is its number.
ACCOUNT = "7"
#: The first two hex digits of a dataflow of process 0, and of process 1, of
#: two (``backend_processes.shard_of``).
HERE, THERE = "00", "01"
#: A portal's source, as Discovery names one.
SOURCE = "chicago-data-portal"


@pytest.fixture()
def start_of_two(tmp_path, monkeypatch):
    """A start of two backend processes, this test's being process 0, with
    a state folder of the start's own."""
    monkeypatch.setenv("CURIO_BACKEND_PROCESSES", "2")
    monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    _forget_every_budget()
    yield
    _forget_every_budget()


@pytest.fixture()
def start_of_one(tmp_path, monkeypatch):
    """A start of one backend process, with a state folder of its own."""
    monkeypatch.delenv("CURIO_BACKEND_PROCESSES", raising=False)
    monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    _forget_every_budget()
    yield
    _forget_every_budget()


def _forget_every_budget() -> None:
    """Each budget's test seam: what this process holds or knows of it."""
    viewer.reset()
    jobs.REGISTRY.reset()
    agent_jobs.reset_registry()
    build_jobs.reset_registry()
    ratelimit.limiter.reset()
    ratelimit.download_slots.reset()
    places.reset()
    backend_runtime.reset_breakers()


def _as_process_one() -> None:
    """In the child: be the start's process 1."""
    os.environ["CURIO_BACKEND_PROCESS"] = "1"


def _refusal(call):
    """What *call* raised, or None when it went through."""
    try:
        call()
    except Exception as exc:  # the test asserts on what it was
        return exc
    return None


def _build_request(note: str):
    return parse_build_request({
        "mode": "create",
        "target": "ai.test.demo@1",
        "manifest": {"id": "ai.test.demo", "compatibility": {"major": 1},
                     "templates": [{"id": "demo-kind"}]},
        "files": {"sources/demo.py": {"text": f"# {note}\nreturn input_0\n"}},
    })


class _Nominatim:
    """Nominatim as a search's transport: one place, and every URL asked."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def json_get(self, url, *, credential=None, headers=None):
        self.urls.append(url)
        return [{
            "name": "Loop", "display_name": "Loop, Chicago, Cook County, Illinois, United States",
            "category": "boundary", "type": "administrative", "osm_type": "relation",
            "boundingbox": ["41.8673", "41.8906", "-87.6382", "-87.6025"],
        }]


def _the_child_holds_every(count: int, take, probe, monkeypatch):
    """The child takes *count* places with *take* and is stopped holding
    them; *probe* then asks for one here; then the child dies, as a crash
    ends a process."""
    window = Window()

    def holds_them_then_dies():
        _as_process_one()
        for _ in range(count):
            take()
        window.stop_here()
        os._exit(9)  # as a crash would: nothing after it runs

    return race(window, holds_them_then_dies, probe, monkeypatch)


def _the_child_holds_one_less_than(cap: int, take, monkeypatch):
    """*take(dataflow)* takes one of an account's *cap* places, for a
    dataflow of the process that takes it. The child takes one less than
    *cap* and is stopped holding them; this process then takes *cap* more,
    so its last is past the cap; then the child dies, as a crash ends a
    process. ``here`` is what each take here raised, or None."""
    window = Window()

    def holds_its_share_then_dies():
        _as_process_one()
        for n in range(cap - 1):
            take(f"{THERE}-{n}")
        window.stop_here()
        os._exit(9)  # as a crash would: nothing after it runs

    def takes_the_rest_and_one_more():
        return [_refusal(functools.partial(take, f"{HERE}-{n}")) for n in range(cap)]

    return race(window, holds_its_share_then_dies, takes_the_rest_and_one_more, monkeypatch)


class TestHeldPlacesAcrossProcesses:
    def test_a_viewers_steps_in_another_process_hold_their_slots_until_it_dies(self, start_of_two, monkeypatch):
        """At most half the sandbox's isolated pool runs a viewer's node at
        once (``viewer.STEP_SLOTS``). Each process had that many slots of its
        own, so the viewers of two dashboards, which two processes own, could
        take the whole pool from the people signed in."""
        def take():
            if not viewer._SLOTS.acquire(timeout=PATIENCE_S):
                raise AssertionError("the other process found no viewer slot free")

        raced = _the_child_holds_every(
            viewer.STEP_SLOTS, take, functools.partial(viewer._SLOTS.acquire, timeout=WAIT_S), monkeypatch,
        )
        if raced.here:
            viewer._SLOTS.release()
        assert raced.here is False, (
            f"this process ran a viewer's step while another process ran {viewer.STEP_SLOTS}, "
            "every slot viewers have"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = viewer._SLOTS.acquire(timeout=PATIENCE_S)
        if again:
            viewer._SLOTS.release()
        assert again is True, "the other process died, and its viewer steps still held their slots"

    def test_package_handlers_in_another_process_hold_their_worker_slots_until_it_dies(self, start_of_two, monkeypatch):
        """At most ``MAX_CONCURRENT_WORKERS`` package handler workers run on
        the machine at once. Each process had that many slots of its own."""
        monkeypatch.setattr(backend_runtime, "_SLOT_WAIT_SECONDS", WAIT_S)
        raced = _the_child_holds_every(
            backend_runtime.MAX_CONCURRENT_WORKERS,
            backend_runtime._acquire_worker_slot,
            functools.partial(_refusal, backend_runtime._acquire_worker_slot),
            monkeypatch,
        )
        if raced.here is None:
            backend_runtime._worker_slots.release()
        assert isinstance(raced.here, backend_runtime.BackendRuntimeError) and raced.here.status == 503, (
            f"this process started a package worker while another process ran "
            f"{backend_runtime.MAX_CONCURRENT_WORKERS}, every slot there is: {raced.here!r}"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _refusal(backend_runtime._acquire_worker_slot)
        if again is None:
            backend_runtime._worker_slots.release()
        assert again is None, f"the other process died, and its workers still held their slots: {again!r}"


class TestAnAccountsCapsAcrossProcesses:
    def test_runs_in_another_process_count_against_the_accounts_cap_until_it_dies(self, start_of_two, monkeypatch):
        """At most ``MAX_ACTIVE_RUNS_PER_USER`` runs go at once on an
        account. Its dataflows sit on different processes, and each process
        counted its own runs alone."""
        cap = jobs.MAX_ACTIVE_RUNS_PER_USER

        def run(dataflow):
            jobs.REGISTRY.register(
                user_key=ACCOUNT, project_id=dataflow, key=dataflow, kind="run", job_id=f"run-{dataflow}",
            )

        raced = _the_child_holds_one_less_than(cap, run, monkeypatch)
        *went, past = raced.here
        assert went == [None] * (cap - 1), went
        assert isinstance(past, jobs.JobRefused) and past.status == 429, (
            f"this process started the account's run past its {cap} while another process ran one: {past!r}"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _refusal(functools.partial(run, f"{HERE}-again"))
        assert again is None, f"the other process died, and its run still counted: {again!r}"

    def test_solves_in_another_process_count_against_the_accounts_cap_until_it_dies(self, start_of_two, monkeypatch):
        """At most ``MAX_ACTIVE_JOBS_PER_USER`` Solves go at once on an
        account, each on the process that owns its dataflow."""
        cap = agent_jobs.MAX_ACTIVE_JOBS_PER_USER

        def solve(dataflow):
            agent_jobs.register_job(
                user_key=ACCOUNT, project_id=dataflow, attachment_id=dataflow,
                kind="solve-batch", job_id=f"solve-{dataflow}",
            )

        raced = _the_child_holds_one_less_than(cap, solve, monkeypatch)
        *went, past = raced.here
        assert went == [None] * (cap - 1), went
        assert isinstance(past, agent_jobs.JobRefused) and past.status == 429, (
            f"this process started the account's Solve past its {cap} while another process ran one: {past!r}"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _refusal(functools.partial(solve, f"{HERE}-again"))
        assert again is None, f"the other process died, and its Solve still counted: {again!r}"

    def test_package_builds_in_another_process_count_against_the_accounts_cap_until_it_dies(
        self, start_of_two, monkeypatch
    ):
        """At most ``MAX_ACTIVE_JOBS_PER_USER`` package builds go at once on
        an account. An agent's build runs in its dataflow's process."""
        cap = build_jobs.MAX_ACTIVE_JOBS_PER_USER

        def build(dataflow):
            build_jobs.create_job(ACCOUNT, _build_request(dataflow))

        raced = _the_child_holds_one_less_than(cap, build, monkeypatch)
        *went, past = raced.here
        assert went == [None] * (cap - 1), went
        assert isinstance(past, build_jobs.JobRefused), (
            f"this process started the account's build past its {cap} while another process ran one: {past!r}"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _refusal(functools.partial(build, f"{HERE}-again"))
        assert again is None, f"the other process died, and its build still counted: {again!r}"

    def test_downloads_in_another_process_count_against_the_accounts_cap_until_it_dies(
        self, start_of_two, monkeypatch
    ):
        """At most ``MAX_CONCURRENT_DOWNLOADS`` Discovery downloads go at once
        on an account. An agent's download runs in its dataflow's process."""
        cap = ratelimit.download_slots.limit

        def download(_dataflow):
            ratelimit.download_slots.acquire(ACCOUNT)

        raced = _the_child_holds_one_less_than(cap, download, monkeypatch)
        *went, past = raced.here
        assert went == [None] * (cap - 1), went
        assert isinstance(past, RateLimited), (
            f"this process started the account's download past its {cap} while another process ran one: {past!r}"
        )
        assert raced.child_exit == 9, f"the other process did not end where it was made to: {raced.child_error}"
        again = _refusal(functools.partial(download, f"{HERE}-again"))
        assert again is None, f"the other process died, and its download still counted: {again!r}"


class TestSpentBudgetsAcrossProcesses:
    def test_runs_another_process_started_from_an_address_spend_its_runs_a_minute(self, start_of_two):
        """A visitor's address starts ``RUNS_PER_ADDRESS_PER_MINUTE`` runs a
        minute. Its dashboards' runs reach the processes that own them, and
        each process spent its own minute. Every call here is at one moment,
        so nothing refills between them."""
        now = time.monotonic()
        address = "203.0.113.9"

        def spends_its_minute():
            _as_process_one()
            for _ in range(viewer.RUNS_PER_ADDRESS_PER_MINUTE):
                if not viewer._LIMITER.allow(address, now):
                    raise AssertionError("the other process was refused a run of the address's minute")

        error = in_another_process(spends_its_minute)
        assert error == "", error
        allowed = viewer._LIMITER.allow(address, now)
        assert allowed is False, (
            f"this process started a run from {address} after another process started "
            f"its {viewer.RUNS_PER_ADDRESS_PER_MINUTE} of the minute"
        )
        elsewhere = viewer._LIMITER.allow("203.0.113.10", now)
        assert elsewhere is True, "another address was refused, though its runs are its own"

    def test_runs_another_process_started_spend_the_minute_every_address_shares(self, start_of_two):
        """All addresses together start ``RUNS_PER_MINUTE`` runs a minute."""
        now = time.monotonic()

        def spends_the_minute():
            _as_process_one()
            for n in range(viewer.RUNS_PER_MINUTE):
                if not viewer._LIMITER.allow(f"10.1.{n // 256}.{n % 256}", now):
                    raise AssertionError("the other process was refused a run of the minute")

        error = in_another_process(spends_the_minute)
        assert error == "", error
        allowed = viewer._LIMITER.allow("192.0.2.1", now)
        assert allowed is False, (
            f"this process started a run after another process started the "
            f"{viewer.RUNS_PER_MINUTE} every address shares in a minute"
        )

    def test_requests_another_process_sent_a_portal_spend_the_accounts_minute_of_it(self, start_of_two):
        """An account sends a portal the requests a minute its manifest
        allows. Dataset Finder searches it from its dataflow's process."""
        per_minute = 2

        def spends_the_minute():
            _as_process_one()
            for _ in range(per_minute):
                ratelimit.limiter.check(ACCOUNT, SOURCE, per_minute)

        error = in_another_process(spends_the_minute)
        assert error == "", error
        refusal = _refusal(functools.partial(ratelimit.limiter.check, ACCOUNT, SOURCE, per_minute))
        assert isinstance(refusal, RateLimited), (
            f"this process sent {SOURCE} a request after another process sent the account's "
            f"{per_minute} of the minute: {refusal!r}"
        )
        another_account = _refusal(functools.partial(ratelimit.limiter.check, "8", SOURCE, per_minute))
        assert another_account is None, (
            f"another account was refused, though its minute is its own: {another_account!r}"
        )

    def test_a_place_search_another_process_sent_holds_this_ones_to_its_turn(self, start_of_two, monkeypatch):
        """Nominatim's policy allows this server one request a second
        (``MIN_INTERVAL_S``). Each process kept its own next second, so two
        processes sent two requests in one. The interval is wide here, so a
        slow runner still searches inside it."""
        monkeypatch.setattr(places, "MIN_INTERVAL_S", 60.0)

        def searches():
            _as_process_one()
            places.search_places(_Nominatim(), "Loop, Chicago")

        error = in_another_process(searches)
        assert error == "", error
        slept: list[float] = []
        monkeypatch.setattr(places.time, "sleep", slept.append)
        transport = _Nominatim()
        found = places.search_places(transport, "Near North Side, Chicago")
        assert found and len(transport.urls) == 1, transport.urls
        assert slept and 0 < slept[0] <= places.MIN_INTERVAL_S, (
            f"this process's search left at once ({slept}) after another process's, "
            f"not {places.MIN_INTERVAL_S:.0f} s after it"
        )

    def test_a_handlers_failures_in_two_processes_count_as_one_run_of_them(self, start_of_two):
        """``QUARANTINE_THRESHOLD`` worker failures in a row quarantine a
        package's handler for an account. Each process counted its own, so a
        crash-looping handler ran that many times in each process, and a
        quarantine in one left the others calling it."""
        key, pin = (ACCOUNT, "ai.test.loops@1", "crash"), "0" * 64

        def fails_all_but_once():
            _as_process_one()
            for _ in range(backend_runtime.QUARANTINE_THRESHOLD - 1):
                backend_runtime._breaker_record(key, pin, infrastructure_failure=True)

        error = in_another_process(fails_all_but_once)
        assert error == "", error
        backend_runtime._breaker_record(key, pin, infrastructure_failure=True)
        remaining = backend_runtime._breaker_check(key, pin)
        assert remaining is not None and 0 < remaining <= backend_runtime.QUARANTINE_SECONDS, (
            f"the handler failed {backend_runtime.QUARANTINE_THRESHOLD} times in a row, all but once in "
            f"another process, and is not quarantined: {remaining!r}"
        )


class TestTheSharedBudgets:
    def test_with_one_process_no_budget_keeps_a_file(self, start_of_one):
        """With one process, every budget is held in its memory as before:
        none writes or reads a file."""
        from utk_curio.backend.app.common import shared_budgets, user_storage

        key, pin = (ACCOUNT, "ai.test.loops@1", "crash"), "0" * 64
        with viewer._SLOTS:
            backend_runtime._acquire_worker_slot()
            backend_runtime._worker_slots.release()
        backend_runtime._breaker_record(key, pin, infrastructure_failure=True)
        quarantined = backend_runtime._breaker_check(key, pin)
        jobs.REGISTRY.register(user_key=ACCOUNT, project_id=HERE, key=HERE, kind="run", job_id="run")
        agent_jobs.register_job(
            user_key=ACCOUNT, project_id=HERE, attachment_id=HERE, kind="solve-batch", job_id="solve",
        )
        build_jobs.create_job(ACCOUNT, _build_request("one process"))
        ratelimit.download_slots.acquire(ACCOUNT)
        ratelimit.download_slots.release(ACCOUNT)
        ratelimit.limiter.check(ACCOUNT, SOURCE, 30)
        allowed = viewer._LIMITER.allow("203.0.113.9", time.monotonic())
        found = places.search_places(_Nominatim(), "Loop, Chicago")
        folder = user_storage.curio_root() / shared_budgets.FOLDER
        assert quarantined is None and allowed is True and found, (quarantined, allowed, found)
        assert not folder.exists(), sorted(str(path) for path in folder.rglob("*"))

    def test_a_place_freed_in_this_process_wakes_its_waiter_at_once(self, start_of_two, monkeypatch):
        """A full budget's waiter looks for a place another process freed
        only every ``RECHECK_S``; one this process frees wakes it at once, as
        a semaphore's release does. The recheck is far longer than the
        waiter waits here, so only that wake can give it the place."""
        from utk_curio.backend.app.common import shared_budgets

        monkeypatch.setattr(shared_budgets, "RECHECK_S", 600.0)
        slots = shared_budgets.Semaphore("wakes-its-waiter", 1)
        taken = slots.acquire(timeout=PATIENCE_S)
        assert taken is True
        got: dict = {}

        def waits():
            started = time.monotonic()
            got["place"] = slots.acquire(timeout=PATIENCE_S / 2)
            got["after"] = time.monotonic() - started

        waiter = threading.Thread(target=waits, daemon=True)
        waiter.start()
        waiter.join(0.2)  # time to find the budget full and wait
        slots.release()
        waiter.join(PATIENCE_S)
        if got.get("place"):
            slots.release()
        assert got.get("place") is True and got["after"] < PATIENCE_S / 4, got

    def test_the_budgets_are_kept_where_only_the_backend_reaches_them(self, start_of_two):
        """Node code runs as another account under isolation. A node that
        could open a holder's lock could hold it, and its place with it."""
        from utk_curio.backend.app.common import shared_budgets, user_storage
        from utk_curio.sandbox.isolation import hardening

        slots = shared_budgets.Semaphore("the-backends-alone", 1)
        taken = slots.acquire(timeout=PATIENCE_S)
        try:
            mode = stat.S_IMODE((user_storage.curio_root() / shared_budgets.FOLDER).stat().st_mode)
        finally:
            if taken:
                slots.release()
        assert taken is True and mode == 0o700, oct(mode)
        sensitive = {relative for relative, _ in hardening.SENSITIVE_PATHS}
        assert f".curio/{shared_budgets.FOLDER}" in sensitive, sorted(sensitive)

    def test_a_start_reads_nothing_the_start_before_it_kept(self, start_of_two, monkeypatch):
        """A budget's state is its start's: a new start begins where one
        process begins, with every budget whole, as before."""
        from utk_curio.backend.app.common import shared_budgets

        state = shared_budgets.State("the-start-before")
        with state.held() as doc:
            doc["spent"] = 3
        with state.held() as doc:
            kept = dict(doc)
        monkeypatch.setattr(shared_budgets, "BOOT_ID", "the next start")
        with state.held() as doc:
            after = dict(doc)
        assert kept == {"spent": 3}, kept
        assert after == {}, after
