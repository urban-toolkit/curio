"""Under --parallel, a shard's state is invisible to every other shard.

Positive proof of isolation, stronger than "the suite passed": a session token
minted on THIS worker's backend must be rejected by every sibling backend. If
two workers ever shared a sqlite file again (a mis-derived CURIO_STATE_DIR, a
DATABASE_URL leaking through the environment), the sibling would accept the
token and this fails -- long before the flaky-401 symptoms that first exposed
the problem would.

Skips in a serial run: with one shard there is nothing to be isolated from.
"""

import json
import urllib.error
import urllib.request

import pytest

from utk_curio.backend.tests.shards import shard_count, shard_index, sibling_backend_urls
from .utils import stub_db_user


def _get(url: str, token: str | None = None) -> int:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_a_token_from_this_shard_is_rejected_by_every_sibling(current_server):
    if shard_count() < 2:
        pytest.skip("needs --parallel: one shard has no siblings to be isolated from")
    me = shard_index()
    siblings = sibling_backend_urls()
    assert siblings, "sharded run but no siblings derived"

    login = stub_db_user(
        current_server,
        username=f"shard_canary_{me}",
        name=f"Shard {me} canary",
    )
    token = login["token"]
    # Sanity: the token is good HERE. Otherwise a 401 below would prove nothing.
    assert _get(f"{current_server}/api/projects", token) == 200

    leaks = []
    for j, url in siblings:
        # Up, so that the rejection below is a rejection and not a dead port.
        assert _get(f"{url}/live") == 200, f"sibling shard {j} at {url} is not up"
        code = _get(f"{url}/api/projects", token)
        if code != 401:
            leaks.append((j, url, code))
    assert not leaks, (
        f"shard {me}'s session token was accepted by sibling(s) {json.dumps(leaks)}: "
        "those shards share a database with this one"
    )
