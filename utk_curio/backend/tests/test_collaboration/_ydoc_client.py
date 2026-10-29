"""A tab's Yjs provider in Python, for the doc tests.

A pycrdt doc that syncs with the server's over a Flask-SocketIO test client, as
the canvas's provider does over socket.io-client: the same ``yjs`` event and
the same y-protocols frames (``collaboration/dataflow_docs.py``). Imported by
the tests' fixtures, never at a test module's top, so a checkout without pycrdt
fails the tests that need it one by one.
"""

from __future__ import annotations

from pycrdt import (
    Array,
    Awareness,
    Doc,
    Map,
    YMessageType,
    YSyncMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    read_message,
)

from ._support import NAMESPACE

EVENT = "yjs"


class DocClient:
    """One tab's doc of one dataflow, over its socket."""

    def __init__(self, socket, project_id: str):
        self.socket = socket
        self.project_id = project_id
        self.doc = Doc()
        self.awareness = Awareness(self.doc)
        self.doc_id = None
        #: The socket's events other than ``yjs``, in the order they came.
        self.events: list = []
        #: Each server step 1 this tab answered, and the ack of its answer.
        self.answers: list = []
        #: Every update the server sent this tab (its step 2 and its
        #: updates), and every update this tab sent, each in order.
        self.received: list[bytes] = []
        self.sent: list[bytes] = []
        self._unsent: list[bytes] = []
        self._remote = False
        self.doc.observe(self._local)

    def _local(self, event) -> None:
        if not self._remote:
            self._unsent.append(event.update)

    def send(self, message: bytes, **extra) -> dict:
        return self.socket.emit(
            EVENT, {"projectId": self.project_id, "message": message, **extra},
            namespace=NAMESPACE, callback=True,
        )

    def sync(self) -> dict:
        """Start the sync, naming the doc it holds, and take what the server sends."""
        extra = {"docId": self.doc_id} if self.doc_id else {}
        ack = self.send(create_sync_message(self.doc), **extra)
        if ack.get("ok"):
            self.doc_id = ack["docId"]
        self.pump()
        return ack

    def pump(self) -> None:
        """Take each message the server sent: apply its updates and awareness,
        and answer its step 1 with what it lacks."""
        for event in self.socket.get_received(NAMESPACE):
            if event["name"] != EVENT:
                self.events.append(event)
                continue
            message = event["args"][0]["message"]
            if message[0] == YMessageType.SYNC and message[1] == YSyncMessageType.SYNC_STEP1:
                answer = handle_sync_message(message[1:], self.doc)
                self.answers.append((answer, self.send(answer)))
            elif message[0] == YMessageType.SYNC:
                self.received.append(read_message(message[2:]))
                self._remote = True
                try:
                    handle_sync_message(message[1:], self.doc)
                finally:
                    self._remote = False
            elif message[0] == YMessageType.AWARENESS:
                self.awareness.apply_awareness_update(read_message(message[1:]), "server")

    def edit(self, change) -> list:
        """Make *change* (a function of the doc) in one transaction, as a
        person's edit, and send its update; the acks."""
        with self.doc.transaction():
            change(self.doc)
        unsent, self._unsent = self._unsent, []
        self.sent += unsent
        return [self.send(create_update_message(update)) for update in unsent]

    def set_presence(self, state) -> dict:
        """Set this tab's awareness state and send it; the ack."""
        self.awareness.set_local_state(state)
        return self.send(create_awareness_message(
            self.awareness.encode_awareness_update([self.doc.client_id])
        ))

    def others(self) -> dict:
        """The awareness states of everyone else, by client id."""
        self.pump()
        return {client: state for client, state in self.awareness.states.items()
                if client != self.doc.client_id}

    def dataflow(self) -> dict:
        from utk_curio.backend.app.collaboration import doc_mapping

        self.pump()
        return doc_mapping.doc_to_dataflow(self.doc)

    def node(self, node_id: str) -> Map:
        return self.doc.get("nodes", type=Map)[node_id]

    def root(self, name: str, kind=Map):
        return self.doc.get(name, type=kind)


def raw_order(doc: Doc, name: str) -> list:
    """An order array as the doc holds it, repeats included."""
    return list(doc.get(name, type=Array))


def synced_tab(application, token: str, project_id: str) -> DocClient:
    """A tab of *project_id* on *application*, signed in with *token*: joined
    to the dataflow's room and synced with its doc, as the canvas is."""
    from ._support import connect, join

    socketio = application.extensions.get("socketio")
    assert socketio is not None, "the app serves no Socket.IO"
    socket = connect(socketio, application, token)
    assert join(socket, project_id)["ok"] is True
    socket.get_received(namespace=NAMESPACE)
    tab = DocClient(socket, project_id)
    ack = tab.sync()
    assert ack["ok"] is True, ack
    return tab


class Origins:
    """The origin of each transaction that changes a root of the server's doc
    of a dataflow, the doc open, in order."""

    def __init__(self, project_id: str, root: str = "nodes"):
        from utk_curio.backend.app.collaboration import dataflow_docs

        entry = dataflow_docs._open_entry(project_id)
        assert entry is not None, "the server holds no doc of the dataflow"
        self.seen: list = []
        self._subscription = entry.doc.get(root, type=Map).observe_deep(
            lambda events: self.seen.append(events[0].transaction.origin)
        )
