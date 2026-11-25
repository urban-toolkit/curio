"""The skill evaluations' agents search where ``CURIO_SEARCH_URL`` says, and each run says where.

``agent_eval.py skills`` (``skill_eval_runner``) starts each worker with its
own environment but the variables that change what the backend is
(``_NOT_INHERITED``), and a worker's web.search reads ``CURIO_SEARCH_URL`` at
each call, as a Curio started with ``--agent-search-url`` does. The Skill
evaluations workflow points it at the job's SearXNG, the service dev and stable
search through, and names that search in ``CURIO_EVAL_SEARCH``.

Each run's ``run.json`` names the search its runs asked (``search``): the URL's
host and port, after the words ``CURIO_EVAL_SEARCH`` gives it, or Curio's
default host when the URL is unset, and never the rest of a URL, where a
provider's key can ride. A URL web.search cannot ask, which ``/api/monitor``
names no provider for, is no search. The report reads it there. Before the
workflow's SearXNG, every run searched Curio's default, whose refusals
research-notes and fact-checking measured, so their numbers compare only with
runs of the same search.

No worker starts here and no model is called. New names are read inside each
test, so this module imports on a checkout without them and each test fails on
its own.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from utk_curio.tools import skill_eval_runner as runner

BASE_URL = "https://models.example.invalid:8443/v1/"
KEY = "sk-test-0123456789abcdef"
#: The URL dev and stable give Curio's --agent-search-url, which the evaluations' web.search asks.
SEARCH_URL = "http://searxng:8080/search?q={q}&format=json"
#: What the Skill evaluations workflow names that search: the service and the image it pins.
NAMED = "SearXNG searxng/searxng:2026.11.11-626105eec"


@pytest.fixture()
def endpoint(monkeypatch):
    """The evaluation endpoint's variables, a commit so no git runs, and no search set."""
    monkeypatch.setenv("CURIO_EVAL_BASE_URL", BASE_URL)
    monkeypatch.setenv("CURIO_EVAL_API_KEY", KEY)
    monkeypatch.setenv("CURIO_EVAL_MODEL", "gemma4")
    monkeypatch.setenv("CURIO_EVAL_COMMIT", "abc123")
    for name in ("CURIO_SEARCH_URL", "CURIO_EVAL_SEARCH", "CURIO_EVAL_GRADER_MODEL"):
        monkeypatch.delenv(name, raising=False)


class _NoWorkers:
    """Workers that run nothing: a run's record is written before its runs start."""

    def __init__(self, *args, **kwargs):
        self.tasks: list = []

    def run(self, tasks) -> None:
        self.tasks = list(tasks)

    def close(self) -> None:
        self.tasks = []


def _recorded(out: Path, monkeypatch) -> tuple[dict, dict, list[Path]]:
    """research-notes' test cases planned once each, on workers that run
    nothing: the run's record, its summary and every file it wrote."""
    monkeypatch.setattr(runner, "_Workers", _NoWorkers)
    args = argparse.Namespace(skills="research-notes", pilot=None, runs=1, jobs=1, only="task", out=out,
                              resume=None, full_trigger_runs=False, hand=False, scope=None)
    # No run has a record, which the runner says and answers 1 for.
    runner.run(args)
    folders = sorted(out.glob("skills-*"))
    assert len(folders) == 1, folders
    record = json.loads((folders[0] / runner.RECORD).read_text(encoding="utf-8"))
    summary = json.loads((folders[0] / "summary.json").read_text(encoding="utf-8"))
    return record, summary, [path for path in folders[0].rglob("*") if path.is_file()]


def test_every_worker_inherits_the_search_url_and_the_name_of_its_search(tmp_path, monkeypatch, endpoint):
    from utk_curio.backend.app.agents.evaluation import skill_evals

    monkeypatch.setenv("CURIO_SEARCH_URL", SEARCH_URL)
    monkeypatch.setenv("CURIO_EVAL_SEARCH", NAMED)
    laid_out = []
    # A worker's packages are a copy of the shipped ones, model weights among them: none is copied here.
    monkeypatch.setattr(runner.shutil, "copytree", lambda source, target, **kwargs: laid_out.append(target))
    workers = runner._Workers(1, tmp_path / "results", skill_evals.Endpoint.from_env(),
                              argparse.Namespace(full_trigger_runs=False, hand=False))
    try:
        env = workers._env(workers.states[0])
    finally:
        workers.close()
    assert laid_out, "the worker's packages were not laid out"
    assert (env.get("CURIO_SEARCH_URL"), env.get("CURIO_EVAL_SEARCH")) == (SEARCH_URL, NAMED)
    assert "CURIO_SEARCH_URL" not in runner._NOT_INHERITED


def test_a_run_records_the_search_its_runs_asked_by_its_name_and_host(tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv("CURIO_SEARCH_URL", SEARCH_URL)
    monkeypatch.setenv("CURIO_EVAL_SEARCH", NAMED)
    record, summary, files = _recorded(tmp_path, monkeypatch)
    assert record.get("search") == f"{NAMED} at searxng:8080", record
    # The run's summary, beside it in the results, says the same.
    assert summary.get("search") == record.get("search")
    # The search names no more of the URL than its host and port.
    assert not [path for path in files if "format=json" in path.read_text(encoding="utf-8")]


def test_with_no_search_url_a_run_records_curio_s_default_and_a_url_s_key_is_written_nowhere(
        tmp_path, monkeypatch, endpoint):
    from utk_curio.backend.app.agents.application import tools

    # A name with no URL is not what web.search asks: Curio's default is.
    monkeypatch.setenv("CURIO_EVAL_SEARCH", NAMED)
    record, _, _ = _recorded(tmp_path / "default", monkeypatch)
    assert record.get("search") == f"{urlsplit(tools.DEFAULT_SEARCH_URL).netloc}, Curio's default", record
    # A provider whose key rides its URL: the record names its host and port alone.
    secret = "sk-search-0123456789abcdef"
    monkeypatch.delenv("CURIO_EVAL_SEARCH")
    monkeypatch.setenv("CURIO_SEARCH_URL", f"https://search.provider.test:8443/v1?api_key={secret}&q={{q}}")
    record, _, files = _recorded(tmp_path / "keyed", monkeypatch)
    assert record.get("search") == "search.provider.test:8443", record
    assert not [path for path in files if secret in path.read_text(encoding="utf-8")]


#: A provider's key, which rides its URL.
SEARCH_KEY = "sk-search-0123456789abcdef"


@pytest.mark.parametrize("url", [
    # No {q}: web.search refuses to search.
    f"https://search.provider.test:8443/v1?api_key={SEARCH_KEY}",
    # A port that is not a number: web.search fails as its provider failing.
    f"http://searxng:80a/search?api_key={SEARCH_KEY}&q={{q}}&format=json",
    # No host: no provider to ask.
    f"/search?api_key={SEARCH_KEY}&q={{q}}&format=json",
], ids=["no-q", "port-not-a-number", "no-host"])
def test_a_url_web_search_cannot_ask_is_recorded_as_no_search(tmp_path, monkeypatch, endpoint, url):
    # The name is of a search the runs never asked: web.search asks none.
    monkeypatch.setenv("CURIO_SEARCH_URL", url)
    monkeypatch.setenv("CURIO_EVAL_SEARCH", NAMED)
    record, summary, files = _recorded(tmp_path, monkeypatch)
    assert record.get("search") == "none, web.search cannot ask CURIO_SEARCH_URL", record
    assert summary.get("search") == record.get("search")
    assert not [path for path in files if SEARCH_KEY in path.read_text(encoding="utf-8")]
