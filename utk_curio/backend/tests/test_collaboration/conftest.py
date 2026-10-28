"""The app the collaboration tests talk to: collaboration on, a fresh database."""

from __future__ import annotations

import pytest

from utk_curio.backend import config as _config
from utk_curio.backend import extensions as _ext
from utk_curio.backend.app import create_app


class _CollabConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def collab_app(monkeypatch):
    """Build a Flask app with ENABLE_COLLAB=True via a config monkeypatch.

    ``create_app`` re-reads ``ENABLE_COLLAB`` from the config module on
    every call (the import is inside the function body), so flipping the
    module attribute before invoking it is enough: no module reload,
    no double SQLAlchemy registration.
    """
    monkeypatch.setattr(_config, "ENABLE_COLLAB", True, raising=True)
    # Drop any singleton left behind by an earlier test invocation.
    monkeypatch.setattr(_ext, "socketio", None, raising=True)

    application = create_app(_CollabConfig)
    socketio = _ext.socketio
    assert socketio is not None, "init_socketio() was not invoked"

    from utk_curio.backend.app.collaboration import room_state

    with application.app_context():
        _ext.db.create_all()
        room_state.reset_for_tests()
        try:
            yield application, socketio, room_state
        finally:
            room_state.reset_for_tests()
            _ext.db.session.remove()
            _ext.db.drop_all()


def _doc_server():
    """The doc server, or ``None`` in a checkout without it, where each doc
    test then fails at its own import or assertion, never here."""
    try:
        from utk_curio.backend.app.collaboration import dataflow_docs
    except ImportError:
        return None
    return dataflow_docs


@pytest.fixture()
def doc_app(monkeypatch, tmp_path):
    """An app as every backend starts, without ``--collab``, whose dataflows'
    folders are in *tmp_path*; its SocketIO server, ``None`` if it serves
    none. The doc server writes a doc only when a test asks it to
    (``flush_due``, ``flush``, ``close``), on a clock the test may set."""
    from utk_curio.backend.app.collaboration import room_state

    docs = _doc_server()
    monkeypatch.setattr(_config, "ENABLE_COLLAB", False, raising=True)
    monkeypatch.setattr(_ext, "socketio", None, raising=True)
    if docs is not None:
        monkeypatch.setattr(docs, "BACKGROUND", False, raising=True)
    application = create_app(_CollabConfig)
    # After the app is made, so its start seeds the packages where it always does.
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))

    with application.app_context():
        _ext.db.create_all()
        room_state.reset_for_tests()
        if docs is not None:
            docs.reset_for_tests()
        try:
            yield application, application.extensions.get("socketio")
        finally:
            if docs is not None:
                docs.reset_for_tests()
            room_state.reset_for_tests()
            _ext.db.session.remove()
            _ext.db.drop_all()
