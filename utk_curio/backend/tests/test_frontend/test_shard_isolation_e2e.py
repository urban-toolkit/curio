"""Under --parallel, a shard's state is invisible to every other shard.

Positive proof of isolation, stronger than "the suite passed": a session token
minted on THIS worker's backend must be rejected by every sibling backend. If
two workers ever shared a sqlite file again (a mis-derived CURIO_STATE_DIR, a
DATABASE_URL leaking through the environment), the sibling would accept the
token and this fails -- long before the flaky-401 symptoms that first exposed
the problem would.

The siblings run their own tests meanwhile, and each resets its database
between them. A reset refuses every request but ``/live`` with 503 until it is
done (``app/testing/in_flight.py``), so a sibling that refuses the token for a
reset is asked again once the reset is over (#1171).

Skips in a serial run: with one shard there is nothing to be isolated from.
"""

import json
import time
import urllib.error
import urllib.request

import pytest

from utk_curio.backend.app.testing.in_flight import REFUSAL, RESET_WAIT_SECONDS
from utk_curio.backend.tests.shards import shard_count, shard_index, sibling_backend_urls
from .utils import stub_db_user

# Only the utk job runs sibling shards (--parallel), so this is the one
# runner where it can do anything but skip (runner_split.py).
pytestmark = pytest.mark.needs_parallel

#: How long a sibling may refuse requests for its resets: a reset waits up to
#: RESET_WAIT_SECONDS for the requests in flight, and the harness gives one
#: 30 s more than that (fixtures._reset_db_via_http).
RESET_BOUND_SECONDS = RESET_WAIT_SECONDS + 30


def _get(url: str, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _get_after_any_reset(url: str, token: str, shard: str) -> int:
    """*url*'s status, asked again while *shard* refuses it for a reset."""
    deadline = time.monotonic() + RESET_BOUND_SECONDS
    while True:
        code, body = _get(url, token)
        if code != 503 or REFUSAL not in body:
            return code
        if time.monotonic() > deadline:
            pytest.fail(
                f"{shard} still refused {url} for a reset of its database "
                f"after {RESET_BOUND_SECONDS:.0f} s"
            )
        time.sleep(0.1)


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
    assert _get(f"{current_server}/api/projects", token)[0] == 200

    leaks = []
    for j, url in siblings:
        # Up, so that the rejection below is a rejection and not a dead port.
        assert _get(f"{url}/live")[0] == 200, f"sibling shard {j} at {url} is not up"
        code = _get_after_any_reset(f"{url}/api/projects", token, f"sibling shard {j} at {url}")
        if code != 401:
            leaks.append((j, url, code))
    assert not leaks, (
        f"shard {me}'s session token was accepted by sibling(s) {json.dumps(leaks)}: "
        "those shards share a database with this one"
    )
