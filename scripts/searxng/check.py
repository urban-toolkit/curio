#!/usr/bin/env python3
"""Ask a search URL one query, as Curio's agents' web.search asks it.

    python scripts/searxng/check.py <URL with {q}> [query]

It prints one line. ``results: N, <size>`` when the URL answers HTTP 200 with
JSON that holds a ``results`` list, in no more than the 256 KiB web.search
reads of an answer, followed, when the list is empty, by the engines SearXNG
says did not answer; it then exits 0. ``failed: <why>`` otherwise, a longer
answer included, and it exits 1.

The deploy runs it in Curio's container once the stack is up, on the URL it
gives Curio's ``--agent-search-url`` (.github/workflows/deploy.yml), and the
Full stack build's bucket-mounts job runs it in a container on the network of
docker-compose.searxng.yml's service. The Skill evaluations workflow runs it
in main's CI image on that network, before its evaluations, which search
there. Standard library only.
"""

from __future__ import annotations

import http.client
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

QUERY = "urban visual analytics"
TIMEOUT_S = 30
#: The most of an answer web.search reads, ``egress.MAX_BODY_BYTES`` in
#: utk_curio/backend/app/agents/infrastructure/egress.py, which a test keeps
#: this equal to: a longer answer reaches the agents cut short, so not as JSON.
MAX_BODY_BYTES = 256 * 1024


def _size(length: int) -> str:
    """*length* bytes as the line gives them: in bytes under 1 KiB, else in whole KiB."""
    return f"{length} bytes" if length < 1024 else f"{length // 1024} KiB"


def check(template: str, query: str = QUERY) -> tuple[bool, str]:
    """Whether *template* answers *query* as a search provider should, and the line that says so."""
    if "{q}" not in template:
        return False, f"failed: {template} has no {{q}} where the query goes"
    url = template.replace("{q}", urllib.parse.quote(query.strip()))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            # One byte past the bound, as web.search reads, tells an answer
            # of exactly the bound from a longer one.
            status, body = response.status, response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as error:
        return False, f"failed: HTTP {error.code} from {url}"
    except (OSError, ValueError, http.client.HTTPException) as error:
        return False, f"failed: {url}: {error}"
    if status != 200:
        return False, f"failed: HTTP {status} from {url}"
    if len(body) > MAX_BODY_BYTES:
        return False, (
            f"failed: HTTP 200 from {url}, an answer over {MAX_BODY_BYTES // 1024} KiB,"
            " the most web.search reads"
        )
    try:
        payload = json.loads(body)
    except ValueError:
        return False, f"failed: HTTP 200 from {url}, not JSON: {body[:200]!r}"
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return False, f"failed: HTTP 200 from {url}, JSON with no results list"
    line = f"results: {len(results)}, {_size(len(body))}"
    if not results:
        # SearXNG lists each engine that did not answer as [engine, why].
        silent = []
        for row in payload.get("unresponsive_engines") or []:
            if isinstance(row, list) and len(row) >= 2:
                silent.append(f"{row[0]} ({row[1]})")
            else:
                silent.append(str(row))
        line += f", no answer from: {', '.join(silent) or 'no engine named'}"
    return True, line


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("failed: usage: check.py <URL with {q}> [query]")
        return 1
    ok, line = check(*argv[1:])
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
