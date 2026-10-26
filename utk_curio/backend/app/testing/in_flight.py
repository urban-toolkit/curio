"""The requests a test rig is serving, so ``reset-db`` can wait for them.

The e2e harness resets the database between tests. A test's page can still
have requests running on the server when it closes: a listing, a dataset's
thumbnails. A reset that deleted their user under them failed every one that
then read the user back (``ObjectDeletedError``, a 500), and one that wrote
afterwards left rows and files for a user that no longer existed, under an id
the next test's account is handed.

So a reset first closes the door: from then on, a new request is refused (the
caller answers 503 with :data:`REFUSAL`) until the reset is done. Then it waits
for the requests already running to finish, and only then deletes. The wait
has a bound, so a request that never ends (a stream nobody reads any more)
cannot stall the suite: the reset then goes ahead under it and names it, and
no later reset waits for it again.

The liveness probe ``/live`` is neither counted nor refused: it reads nothing a
reset deletes, and a backend that is resetting is up.

Only a test rig builds one of these (``testing/routes.py``), so a server
started without ``CURIO_TESTING`` counts nothing.
"""

from __future__ import annotations

import threading

#: How long a reset waits for the requests running when it starts. A page's
#: workflow dependency check alone took up to 9.4 s on CI.
RESET_WAIT_SECONDS = 30.0

#: The ``error`` of the 503 a request gets while a reset runs. A client that
#: may ask in the middle of another test's reset (the shard isolation e2e asks
#: the other shards) asks again when it gets this.
REFUSAL = "The test database is being reset."


class InFlightRequests:
    """The requests one app is serving, and whether a reset has closed the door."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._running: dict[object, str] = {}
        self._closed = False

    def enter(self, label: str) -> object | None:
        """Count a request in and return its token, or None while a reset runs."""
        with self._cond:
            if self._closed:
                return None
            token = object()
            self._running[token] = label
            return token

    def leave(self, token: object) -> None:
        """Count a request out."""
        with self._cond:
            if self._running.pop(token, None) is not None:
                self._cond.notify_all()

    def close(self) -> list[str]:
        """Refuse new requests, once any reset already running is done.
        Returns the requests running now."""
        with self._cond:
            self._cond.wait_for(lambda: not self._closed)
            self._closed = True
            return sorted(self._running.values())

    def drain(self, timeout: float) -> list[str]:
        """Wait up to *timeout* seconds for the running requests to finish.

        Returns those still running. They are forgotten: they have outlived
        this reset, and a later one does not wait for them again.
        """
        with self._cond:
            self._cond.wait_for(lambda: not self._running, timeout=timeout)
            still_running = sorted(self._running.values())
            self._running.clear()
            return still_running

    def open(self) -> None:
        """Let requests in again."""
        with self._cond:
            self._closed = False
            self._cond.notify_all()
