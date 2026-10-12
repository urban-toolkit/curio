"""The backend's HTTP client for the sandbox.

One pooled session, the sandbox's address, and :func:`sandbox_request`, which
attaches the shared secret and turns a transport failure into a
:class:`SandboxTransportError`. The API routes answer that error as JSON
(``api/routes.py`` ``_sandbox_call``); a caller with no request, such as a node
run on a thread of its own, reads it as the sandbox being unavailable.
"""

from __future__ import annotations

import os
import threading

import requests

from utk_curio.backend.app.execution.sandbox_auth import sandbox_headers

_sandbox_session = requests.Session()

# The sandbox takes so many runs at once and makes the others wait inside it,
# answering nothing until a run ends, so a request that waited there spent its
# timeout waiting (#863, #889). The backend's runs take as many turns here,
# before they are sent: one set per endpoint and size, made on first use.
_turns: dict[tuple[str, int], threading.BoundedSemaphore] = {}
_turns_lock = threading.Lock()

# Sandbox address
api_address = 'http://' + os.getenv('FLASK_SANDBOX_HOST', '127.0.0.1')
api_port = int(os.getenv('FLASK_SANDBOX_PORT', 2000))


class SandboxTransportError(Exception):
    """The sandbox could not be asked: it timed out, was unreachable, or
    refused the backend's shared secret.

    ``payload`` is the JSON body the routes answer with and ``status`` its HTTP
    status, so every caller reports the same words the browser has always seen.
    """

    def __init__(self, payload: dict, status: int):
        super().__init__(payload.get('message') or payload.get('error'))
        self.payload = payload
        self.status = status


def exec_turn(endpoint: str) -> threading.BoundedSemaphore:
    """Wait here for the sandbox to have room for a run on *endpoint*
    (``/exec`` or ``/execJs``) before the request is sent.

    The sandbox would make the request wait for its place, and the request's
    timeout would count that wait; taken here, the timeout starts when the
    sandbox can run the node, so it covers the node's own run. There are as
    many turns as the sandbox has places, counted where the sandbox counts
    them, so as many runs as before are in the sandbox at once:

    - ``/exec`` without isolation: one, the sandbox's ``_exec_lock``;
    - ``/exec`` with isolation: ``CURIO_EXEC_PARALLELISM``, its isolated slots;
    - ``/execJs``, in both modes: ``CURIO_JS_PARALLELISM``, its Node slots.
    """
    from utk_curio.backend.app.discovery.infrastructure.media_dirs import isolation_on
    from utk_curio.sandbox import concurrency

    if endpoint == "/execJs":
        places = concurrency.js_parallelism()
    elif isolation_on():
        places = concurrency.exec_parallelism()
    else:
        places = 1
    with _turns_lock:
        turn = _turns.get((endpoint, places))
        if turn is None:
            turn = _turns[(endpoint, places)] = threading.BoundedSemaphore(places)
    return turn


def sandbox_request(method: str, path: str, *, label: str, timeout: int, **kwargs) -> requests.Response:
    """Call the sandbox over the pooled session with consistent error handling.

    Raises :class:`SandboxTransportError` for ``requests.Timeout`` and
    ``requests.ConnectionError`` instead of letting them escape (which would
    otherwise surface to the browser as an opaque 'NetworkError when attempting
    to fetch resource').

    Also attaches the sandbox shared secret, and translates the sandbox's 401
    into a clear error rather than letting callers hit it as an unparseable
    body (`/get` would report it as 'Error loading artifact', `/exec` as
    'sandbox returned non-JSON' plus a 500).

    Returns the `requests.Response` on success, so callers can parse the JSON
    or forward it as before.
    """
    url = api_address + ":" + str(api_port) + path
    fn = getattr(_sandbox_session, method)
    kwargs['headers'] = sandbox_headers(kwargs.get('headers'))
    try:
        response = fn(url, timeout=timeout, **kwargs)
    except requests.Timeout as e:
        print(f"[backend {label}] sandbox call timed out after {timeout}s: {e}", flush=True)
        raise SandboxTransportError({
            'error': 'sandbox_timeout',
            'message': (f'The sandbox did not respond within {timeout}s on {path}. '
                        'The node is likely still running - check the sandbox log. '
                        'For large data loads, consider trimming columns or rows '
                        'before returning from the node.'),
            'path': path,
            'timeout_seconds': timeout,
        }, 504) from e
    except requests.ConnectionError as e:
        print(f"[backend {label}] sandbox connection error on {path}: {e}", flush=True)
        raise SandboxTransportError({
            'error': 'sandbox_unreachable',
            'message': (f'Could not reach the sandbox on {path}. '
                        'Check that the sandbox process is running '
                        f'({api_address}:{api_port}).'),
            'path': path,
        }, 502) from e

    if response.status_code == 401:
        print(f"[backend {label}] sandbox rejected the shared secret on {path}", flush=True)
        # A streamed call holds its pooled connection until the body is read.
        response.close()
        raise SandboxTransportError({
            'error': 'sandbox_unauthorized',
            'message': (f'The sandbox rejected the backend on {path}. The two '
                        'processes disagree about CURIO_SANDBOX_TOKEN - this '
                        "usually means one of them was started outside "
                        "'curio start' or was restarted without the other."),
            'path': path,
        }, 502)

    return response
