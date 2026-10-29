"""How every backend's Socket.IO server runs a socket's events, and sends to it.

One at a time, in the order the socket sent them, on the thread that reads
that socket, as Flask-SocketIO's test client runs them for every other test
here: it turns off the server's thread per event on the server it drives. With
python-socketio's default, a thread per event, the backend's threads grew with
the rate of events rather than with its sockets, and the stress tiers' 100
tabs typing at once took the stack's container to its task limit (run
40761228867): new threads failed in the backend, the sandbox and node runs
beside it, and the updates whose threads never started were lost.

And each message reaches its client whole: the test client replaces the
server's sends with its own, so this is the one place they are tested.
"""

from __future__ import annotations

import threading
import time


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


def test_a_doc_message_reaches_its_client_whole_while_another_thread_answers_that_client(doc_app, monkeypatch):
    """A doc message is a binary event: python-socketio puts its header and
    its attachment on the client's queue one at a time, and its sends are not
    thread safe. While the doc's thread relays to a socket, that socket's own
    thread answers its updates, and an answer landing between the relay's two
    packets is a broken stream to the client, whose socket.io-client closes the
    connection on it. Every send to a client takes its lock, and a relay holds
    it across its packets: the answer waits for the relay's last packet."""
    from socketio import packet

    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.config import COLLAB_NAMESPACE

    _application, socketio = doc_app
    assert socketio is not None, "every backend serves Socket.IO"
    server = socketio.server
    sid = server.manager.connect("tab-socket", COLLAB_NAMESPACE)
    put: list = []
    header_put = threading.Event()
    answering = threading.Event()

    def held_after_the_header(eio_sid, pkt):
        put.append(pkt.data)
        if len(put) == 1:
            header_put.set()
            answering.wait(5)
            time.sleep(0.2)  # the answer's own put, unless something holds it back

    monkeypatch.setattr(server.eio, "send_packet", held_after_the_header)
    relay = threading.Thread(target=dataflow_docs._emit, args=(b"\x00\x02\x01x", "a-dataflow"), kwargs={"to": sid})
    relay.start()
    assert header_put.wait(5), "the relay put nothing"

    def answer():
        answering.set()
        server._send_packet("tab-socket", packet.Packet(packet.ACK, namespace=COLLAB_NAMESPACE, id=1,
                                                        data=[{"ok": True, "queued": True}]))

    answerer = threading.Thread(target=answer)
    answerer.start()
    relay.join(5)
    answerer.join(5)
    assert not relay.is_alive() and not answerer.is_alive()
    kinds = ["attachment" if isinstance(data, bytes) else int(str(data)[0]) for data in put]
    assert kinds == [packet.BINARY_EVENT, "attachment", packet.ACK], (
        f"the client got {kinds}: an answer landed between the relay's packets"
    )
