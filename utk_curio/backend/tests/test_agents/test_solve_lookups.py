"""A plan's Solve looks up the Data Catalog one round at a time.

Each round of a plan's Solve looks up the paths of the datasets its code
reads, on the pool's thread that solves its node (the ``dataset_paths_fn``
``SolveBatch`` hands its rounds, ``grounding._session_dataset_paths``), and
the nodes of one wave start their rounds together. Their lookups share the
Solve's paths and the downloads that failed in its run, so they go one at a
time:

- No two of a Solve's lookups run at once. The unit suites' in-memory
  database gives every thread one SQLite connection, and two lookups on it at
  once crashed the backend's unit tests: in run 44067161334, unit
  (backend-1), two of a Solve's threads were in ``resolve_execution_paths``
  together, and one segfaulted reading the dataset index
  (``index.list_for_user``).
- A dataset two nodes read at once whose download fails is asked for once:
  the second lookup comes after the first and finds the failure the Solve
  keeps.

Each test holds the first lookup until both nodes' rounds have asked for
their datasets, then a few seconds more or until a second lookup starts
beside it (``_Lookups``), so a Solve whose lookups can meet meets them on
every run. Each lookup itself still runs alone, under the test's own lock: a
Solve that looks two up at once fails here on the count, and does not take
the test process down on the shared connection.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

import json
import threading

DL = "curio.builtin/data-loading"
#: The loaders' intents. A node's own intent keys its scripted reply
#: (``InProcessDriver.delegate_inputs``): its request names its siblings too.
HEAT = "load the tract heat table"
RAIN = "load the tract rain table"


class _Lookups:
    """The Data Catalog lookups of a Solve's rounds, held so two of them can meet.

    A round asking for its datasets is counted (:meth:`asked`), and so is each
    lookup (``resolve_execution_paths``, :meth:`look_up`). The first lookup
    made once a round has asked waits until *rounds* rounds have asked, then
    up to :data:`BESIDE_IT_WITHIN_S` for a second lookup to start beside it.
    """

    #: How long the first lookup waits for the other rounds to ask.
    ASKED_WITHIN_S = 60
    #: Then how long it waits for a second lookup to start beside it.
    BESIDE_IT_WITHIN_S = 3

    def __init__(self, rounds: int):
        self.rounds = rounds
        self.changed = threading.Condition()
        self.askers: list[str] = []
        self.lookups: list[tuple[str, list]] = []
        self.inside: list[str] = []
        self.most_at_once: list[str] = []
        self.held = False
        self.alone = threading.Lock()

    def asked(self) -> None:
        with self.changed:
            self.askers.append(threading.current_thread().name)
            self.changed.notify_all()

    def look_up(self, lookup, dataset_ids):
        me = threading.current_thread().name
        with self.changed:
            self.lookups.append((me, list(dataset_ids or [])))
            self.inside.append(me)
            if len(self.inside) > len(self.most_at_once):
                self.most_at_once = list(self.inside)
            self.changed.notify_all()
            if self.askers and not self.held:
                self.held = True
                self.changed.wait_for(lambda: len(set(self.askers)) >= self.rounds, timeout=self.ASKED_WITHIN_S)
                self.changed.wait_for(lambda: len(self.inside) > 1, timeout=self.BESIDE_IT_WITHIN_S)
        try:
            with self.alone:
                return lookup()
        finally:
            with self.changed:
                self.inside.remove(me)
                self.changed.notify_all()

    def watch(self, monkeypatch) -> None:
        """Count every round's ask, through the ``dataset_paths_fn`` the
        batch hands its rounds, and hold every lookup of the Data Catalog."""
        from utk_curio.backend.app.agents.application.solve import rounds
        from utk_curio.backend.app.datasets.application.catalog_service import DatasetCatalogService

        lookups = self
        rounds_of = rounds._verified_content_rounds
        resolve = DatasetCatalogService.resolve_execution_paths

        def counted_rounds(*args, **kwargs):
            batch_paths = kwargs.get("dataset_paths_fn")
            if batch_paths is not None:
                def asking(codes, formats, unavailable=None):
                    lookups.asked()
                    return batch_paths(codes, formats, unavailable)

                kwargs["dataset_paths_fn"] = asking
            return rounds_of(*args, **kwargs)

        def held_resolve(service, dataset_ids, *args, **kwargs):
            return lookups.look_up(lambda: resolve(service, dataset_ids, *args, **kwargs), dataset_ids)

        monkeypatch.setattr(rounds, "_verified_content_rounds", counted_rounds)
        monkeypatch.setattr(DatasetCatalogService, "resolve_execution_paths", held_resolve)

    def met(self) -> str:
        return (
            f"{len(self.most_at_once)} of the Solve's lookups ran at once "
            f"(on {', '.join(self.most_at_once)}; every lookup: {self.lookups}): in the unit "
            "suites' in-memory database every thread shares one SQLite connection, on which "
            "two lookups at once segfaulted run 44067161334's unit (backend-1)"
        )


def _two_loaders_plan(with_stats=True):
    """A plan of two data-loading nodes that share no edge, so one wave holds both."""
    nodes = [
        {"ref": "heat", "nodeType": DL, "title": "Heat", "intent": HEAT},
        {"ref": "rain", "nodeType": DL, "title": "Rain", "intent": RAIN},
    ]
    plan = {"goal": "heat and rain by tract", "nodes": nodes, "edges": []}
    return "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _two_loaders(client, user, token, monkeypatch, loaders):
    """The plan of two loaders, landed as ``TestVerifiedSolve._setup`` lands
    its plan, with its fake sandbox; then each loader's Solve answered with
    the code *loaders* gives for its intent, ``{DATASET}`` in it being the
    dataset ``_setup`` seeds. ``(solve, ctx)``."""
    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds
    from utk_curio.backend.tests.test_agents._reconstruction_driver import InProcessDriver

    solve = verified_rounds.TestVerifiedSolve()
    solve._plan_tail = _two_loaders_plan
    ctx = solve._setup(client, user, token, monkeypatch, dl_replies=[solve.LOADER], with_stats=False)
    replies = {intent: code.replace("{DATASET}", ctx["dataset_id"]) for intent, code in loaders.items()}

    def _reply(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        if "[delegated task" not in (messages[-1].get("content") or ""):
            return _two_loaders_plan()
        return replies[InProcessDriver.delegate_inputs(messages).get("intent")]

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _reply)
    return solve, ctx


def test_a_plans_rounds_look_their_datasets_up_one_at_a_time(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """Two loaders in one wave, each reading a dataset of the account's own.
    Each round looks its dataset up, and never while the other's lookup
    runs; both run with their paths."""
    from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    rain = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="rain_tracts.csv")
    loader = verified_rounds.TestVerifiedSolve.LOADER
    solve, ctx = _two_loaders(
        client, user, token, monkeypatch, {HEAT: loader, RAIN: loader.replace("{DATASET}", rain)},
    )
    heat = ctx["dataset_id"]
    lookups = _Lookups(rounds=2)
    lookups.watch(monkeypatch)

    body = solve._solve(client, token, ctx)

    assert len(set(lookups.askers)) >= 2, f"not both loaders' rounds asked for their datasets: {lookups.askers}"
    looked_up = sorted(dataset_id for _thread, ids in lookups.lookups for dataset_id in ids)
    assert looked_up == sorted([heat, rain]), f"each dataset is looked up once: {lookups.lookups}"
    assert len(lookups.most_at_once) == 1, lookups.met()
    results = body["results"]
    assert len(results) == 2 and all(result["status"] == "solved" for result in results.values()), results
    handed = {dataset_id for payload in ctx["exec_payloads"] for dataset_id in payload.get("dataset_paths") or {}}
    assert handed == {heat, rain}, ctx["exec_payloads"]


def test_a_dataset_two_nodes_read_at_once_whose_download_fails_is_asked_for_once(
    client, user_and_token, tmp_curio, tmp_path, monkeypatch,
):
    """Both loaders of one wave read the shipped dataset a pip install leaves
    out, and its download fails. The Solve asks for it once: the second
    lookup comes after the first and finds the failure the Solve keeps for
    its run. Each node says why in one attempt, and the sandbox is never
    asked to run a loader whose dataset could not be had."""
    from utk_curio.backend.tests._support.left_out_files import FakeGitHub, url_of
    from utk_curio.backend.tests.test_agents import test_solve_downloads as downloads

    user, token = user_and_token
    github = downloads._as_a_pip_install(tmp_path, monkeypatch, FakeGitHub(fail=OSError("Network is unreachable")))
    solve, ctx = _two_loaders(client, user, token, monkeypatch, {HEAT: downloads._loading(), RAIN: downloads._loading()})
    lookups = _Lookups(rounds=2)
    lookups.watch(monkeypatch)

    body = solve._solve(client, token, ctx)

    assert len(set(lookups.askers)) >= 2, f"not both loaders' rounds asked for their datasets: {lookups.askers}"
    assert github.urls == [url_of(downloads.MRT)], (
        f"the Solve asked for the dataset {len(github.urls)} times: {github.urls}; every lookup: {lookups.lookups}"
    )
    assert len(lookups.most_at_once) == 1, lookups.met()
    results = body["results"]
    assert len(results) == 2, results
    for result in results.values():
        assert result["status"] == "failed", result
        attempts = result.get("attempts") or []
        assert len(attempts) == 1, f"the node said why in {len(attempts)} attempts: {attempts}"
        for words in (downloads.MRT, "Network is unreachable"):
            assert words in (attempts[0].get("stderrTail") or ""), attempts[0]
    assert ctx["exec_payloads"] == [], "the sandbox was asked to run a loader whose dataset could not be had"
