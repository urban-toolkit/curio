"""``scripts/searxng/check.py``: one query to a search URL, read as web.search reads it.

The deploy and the Full stack build's bucket-mounts job run the script on the
URL Curio's agents search. web.search reads at most ``egress.MAX_BODY_BYTES``
of an answer, one byte past it to tell a longer answer, and a longer answer
reaches the agents cut short, which does not parse as JSON. So the check reads
no more than that either, and fails a longer answer. A passing line gives the
count, then the answer's size, then, with no results, the engines that did not
answer; the deploy warns on ``results: 0,`` anywhere in what the check printed.

No test opens a socket: ``urllib.request.urlopen`` hands the script an answer
from bytes in memory (``_Answer``), which fails the test when read whole.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.request
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.infrastructure import egress

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "searxng" / "check.py"
#: The URL each hosted stack gives Curio's --agent-search-url, and the URL the
#: check asks with its own query.
TEMPLATE = "http://searxng:8080/search?q={q}&format=json"
URL = "http://searxng:8080/search?q=urban%20visual%20analytics&format=json"
CAP = egress.MAX_BODY_BYTES


@pytest.fixture()
def script():
    """The check, loaded by its path, as the deploy runs it."""
    spec = importlib.util.spec_from_file_location("_scripts_searxng_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Answer:
    """What the fake ``urlopen`` hands the script: HTTP 200 with *body*, each
    read giving at most the bytes it asks for, as ``http.client`` reads. A
    read with no bound fails the test; ``handed`` counts the bytes read."""

    status = 200

    def __init__(self, body: bytes):
        self._body = io.BytesIO(body)
        self.handed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=None):
        if amount is None or amount < 0:
            raise AssertionError("the check read the whole answer, with no bound")
        chunk = self._body.read(amount)
        self.handed += len(chunk)
        return chunk


def _json_of(size: int, results: int, **fields) -> bytes:
    """JSON of exactly *size* bytes, shaped as SearXNG's answer: *results*
    rows, then *fields*, then a field that pads it."""
    rows = [
        {"title": f"Result {i}", "url": f"https://example.org/{i}", "content": "A snippet."}
        for i in range(results)
    ]
    payload = {"query": "urban visual analytics", "results": rows, **fields, "padding": ""}
    unpadded = len(json.dumps(payload).encode())
    assert unpadded <= size
    payload["padding"] = "x" * (size - unpadded)
    body = json.dumps(payload).encode()
    assert len(body) == size
    return body


def _run(script, monkeypatch, capsys, body: bytes):
    """``(exit code, what it printed, the answer)`` of the check asking
    TEMPLATE, answered with *body*."""
    answer = _Answer(body)
    asked = []

    def urlopen(url, timeout=None):
        asked.append((url, timeout))
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    code = script.main(["check.py", TEMPLATE])
    assert asked == [(URL, script.TIMEOUT_S)]
    return code, capsys.readouterr().out, answer


def test_the_check_reads_at_most_what_web_search_reads(script):
    assert script.MAX_BODY_BYTES == egress.MAX_BODY_BYTES


@pytest.mark.parametrize("size", [CAP + 1, 3 * CAP], ids=["one-byte-over", "three-times-over"])
def test_an_answer_over_the_cap_fails_read_one_byte_past_it(script, monkeypatch, capsys, size):
    """JSON with 45 results, which only its size keeps from the agents: the
    check reads one byte past the cap, as web.search does, and no more."""
    code, out, answer = _run(script, monkeypatch, capsys, _json_of(size, 45))
    assert (code, out) == (
        1,
        f"failed: HTTP 200 from {URL}, an answer over 256 KiB, the most web.search reads\n",
    )
    assert answer.handed == CAP + 1


def test_an_answer_of_exactly_the_cap_passes(script, monkeypatch, capsys):
    """web.search takes an answer of exactly the cap whole, so the check passes it."""
    body = _json_of(CAP, 1)
    assert len(body) == 256 * 1024
    code, out, answer = _run(script, monkeypatch, capsys, body)
    assert (code, out) == (0, "results: 1, 256 KiB\n")
    assert answer.handed == CAP


def test_a_json_answer_passes_with_its_count_and_size(script, monkeypatch, capsys):
    body = _json_of(38 * 1024 + 500, 45, unresponsive_engines=[])
    code, out, _ = _run(script, monkeypatch, capsys, body)
    assert (code, out) == (0, "results: 45, 38 KiB\n")


def test_no_results_keep_the_engines_that_did_not_answer(script, monkeypatch, capsys):
    """The line starts with ``results: 0,``, which the deploy warns on, and
    names each engine SearXNG says did not answer, with why."""
    body = _json_of(600, 0, unresponsive_engines=[["google", "timeout"], ["brave", "too many requests"]])
    code, out, _ = _run(script, monkeypatch, capsys, body)
    assert (code, out) == (
        0,
        "results: 0, 600 bytes, no answer from: google (timeout), brave (too many requests)\n",
    )
