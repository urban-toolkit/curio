"""How every backend's Socket.IO server runs a socket's events.

One at a time, in the order the socket sent them, on the thread that reads
that socket, as Flask-SocketIO's test client runs them for every other test
here: it turns off the server's thread per event on the server it drives. With
python-socketio's default, a thread per event, the backend's threads grew with
the rate of events rather than with its sockets, and the stress tiers' 100
tabs typing at once took the stack's container to its task limit (run
40761228867): new threads failed in the backend, the sandbox and node runs
beside it, and the updates whose threads never started were lost.
"""

from __future__ import annotations

import threading


def test_a_sockets_events_run_one_at_a_time_in_order_on_the_thread_that_reads_it(doc_app):
    _application, socketio = doc_app
    assert socketio is not None, "every backend serves Socket.IO"
    # The server as create_app made it: no test client has touched it.
    server = socketio.server
    handled = []
    server.on("probe", lambda _sid, n: handled.append((threading.get_ident(), n)), namespace="/probe")
    assert server.manager.connect("probe-socket", "/probe") is not None

    for n in range(3):
        server._handle_event("probe-socket", "/probe", None, ["probe", n])

    assert handled == [(threading.get_ident(), n) for n in range(3)], (
        "each event ran on a thread of its own, so a burst of events is a burst of threads"
    )
