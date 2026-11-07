"""How long a connection may take to send the head of its request.

Curio's servers answer through ``http.server`` request handlers: Werkzeug's
under the backend, the standard library's under the page server. Both wait for
a request line with no timeout, so a client that connects and then sends
nothing, a port scanner or a dropped network, holds a socket and a thread until
the server stops. On 11-06 such connections filled the hosted stable backend's
1024 open files, and every request after them failed with "Too many open
files".

``RequestHeadDeadline`` gives each request ``request_start_timeout`` seconds,
from the moment its connection waits for it until its headers are in, then
lifts the timeout. A body being read, a reply being streamed, an event stream
and a WebSocket keep their connection as before.
"""

#: Seconds a connection may take to send a request line and its headers.
REQUEST_START_TIMEOUT_S = 60


class RequestHeadDeadline:
    """Mixin for a ``http.server.BaseHTTPRequestHandler``, listed before it."""

    request_start_timeout = REQUEST_START_TIMEOUT_S

    def handle_one_request(self):
        self.connection.settimeout(self.request_start_timeout)
        try:
            # The first byte of the request, or the client's close.
            self.rfile.peek(1)
        except TimeoutError:
            # Nothing came: the connection ends quietly, as an idle keep-alive
            # connection does. A stall inside the head is logged by
            # http.server's own handling of the timeout.
            self.close_connection = True
            return
        super().handle_one_request()

    def parse_request(self):
        parsed = super().parse_request()
        self.connection.settimeout(None)
        return parsed
