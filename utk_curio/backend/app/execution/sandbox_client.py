"""The backend's HTTP client for the sandbox.

One pooled session, the sandbox's address, and :func:`sandbox_request`, which
attaches the shared secret and turns a transport failure into a
:class:`SandboxTransportError`. The API routes answer that error as JSON
(``api/routes.py`` ``_sandbox_call``); a caller with no request, such as a node
run on a thread of its own, reads it as the sandbox being unavailable.
"""

from __future__ import annotations

import os

import requests
from urllib3.exceptions import ReadTimeoutError

from utk_curio.backend.app.execution.sandbox_auth import sandbox_headers

_sandbox_session = requests.Session()

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


def read_timed_out(exc: Exception) -> bool:
    """Whether a request to the sandbox failed on its read timeout.

    requests counts the timeout on every gap between the reply's bytes. A gap
    before the headers raises ``requests.Timeout``; a gap inside the body
    raises ``requests.ConnectionError`` around urllib3's ``ReadTimeoutError``.
    ``/exec`` and ``/execJs`` answer at once and keep the connection busy while
    a run waits for its place (#889), so a run that outlasts its timeout ends
    as the second.
    """
    if isinstance(exc, requests.Timeout):
        return True
    return isinstance(exc, requests.ConnectionError) and any(
        isinstance(cause, ReadTimeoutError) for cause in exc.args
    )


def sandbox_request(method: str, path: str, *, label: str, timeout: int, **kwargs) -> requests.Response:
    """Call the sandbox over the pooled session with consistent error handling.

    Raises :class:`SandboxTransportError` for a timeout (:func:`read_timed_out`),
    ``requests.ConnectionError`` and a reply cut short instead of letting them
    escape (which would otherwise surface to the browser as an opaque
    'NetworkError when attempting to fetch resource').

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
    except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
        if read_timed_out(e):
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
        # Unreachable, or a reply cut short: the sandbox went away mid-run (#889).
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
