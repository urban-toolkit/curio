"""What a dataflow's room hears by role: a change to its editors, and what
only those who edit it hear.

``projects/access.py`` calls :func:`set_user_role` after it adds or removes an
editor, so the account's participants edit or watch at once, without joining
again. A removed editor's locks go with their edit rights. Nothing happens
when the account is not in the room. :func:`tell_editors` tells only the tabs
of the owner and the editors, as an agent's chat turns reach them
(``agents/application/turns/turn_jobs.py``): a watcher's tab hears nothing.
A word each tab answers with a read (:class:`PacedWord`) is told at once,
then at most once more per dataflow per wait: what changed during the wait
is told, in one word, when it ends.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from utk_curio.backend.app.collaboration import room_state

log = logging.getLogger(__name__)


def set_user_role(project_id: str, user_id, role: str) -> bool:
    """Give *user_id*'s participants in *project_id*'s room *role*, and tell
    the room. Whether anyone's role changed."""
    from utk_curio.backend import extensions
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = extensions.socketio
    if sio is None:
        return False
    room = room_state.room_for(project_id)
    changed, released = room_state.set_user_role(room, user_id, role)
    if not changed:
        return False
    for node_id in released:
        sio.emit("node_unlocked", {"nodeId": node_id}, to=room, namespace=COLLAB_NAMESPACE)
    sio.emit("roles_changed", {"users": room_state.users_in(room)}, to=room, namespace=COLLAB_NAMESPACE)
    room_state.record_activity(room, "role_changed", {"user_id": user_id, "role": role})
    return True


def tell_editors(project_id: str, event: str, payload: dict, *, app=None) -> int:
    """Tell *event* with *payload* to the tabs in *project_id*'s room that
    edit the dataflow, its owner's and its editors', each tab's role read now:
    a watcher's tab is told nothing. *app* is the app whose SocketIO server
    sends it, for a thread that holds no app context; else the app at hand's,
    else the backend's. How many tabs were told."""
    from utk_curio.backend import extensions
    from utk_curio.backend.config import COLLAB_NAMESPACE

    sio = (app.extensions.get("socketio") if app is not None else None) or _app_socketio() or extensions.socketio
    if sio is None:
        return 0
    sids = room_state.edit_sids(room_state.room_for(project_id))
    for sid in sids:
        sio.emit(event, payload, to=sid, namespace=COLLAB_NAMESPACE)
    return len(sids)


def _app_socketio():
    """The SocketIO server of the app at hand, if any."""
    from flask import current_app, has_app_context

    return current_app.extensions.get("socketio") if has_app_context() else None


def _app_at_hand():
    """The app of the request or job at hand, for a word told when a wait
    ends, on the wait's own thread, which holds no app context."""
    from flask import current_app, has_app_context

    return current_app._get_current_object() if has_app_context() else None


@dataclass
class _Wait:
    """A dataflow's wait after a word: whether a change came during it, and
    what changed (:attr:`PacedWord.names`), told when it ends, and the app
    to tell it with."""

    timer: threading.Timer
    changed: bool = False
    names: list = field(default_factory=list)
    app: object = None


class PacedWord:
    """A word told to the tabs that edit a dataflow (:func:`tell_editors`),
    each of which reads something again when told: told at once, then at
    most once more per dataflow every *every_s()* seconds. What changed
    during a wait, a burst's last change among it, is told in one word when
    the wait ends. Its payload is ``{projectId}``, and, when *names* is
    given, what changed since the last word under that key, each once, in
    the order it changed: ``agent_chat_changed`` names the chats."""

    def __init__(self, event: str, every_s: Callable[[], float], names: Optional[str] = None):
        self.event = event
        self.every_s = every_s
        self.names = names
        self._waits: dict[str, _Wait] = {}
        self._lock = threading.Lock()

    def tell(self, project_id: str, name: Optional[str] = None) -> None:
        """*name* of *project_id*'s changed: told now, or when the wait
        after the last word ends."""
        app = _app_at_hand()
        with self._lock:
            wait = self._waits.get(project_id)
            if wait is not None:
                wait.changed = True
                if name is not None and name not in wait.names:
                    wait.names.append(name)
                wait.app = app or wait.app
                return
            self._waits[project_id] = _Wait(self._wait_after_word(project_id), app=app)
        self._say(project_id, [] if name is None else [name], app)

    def _wait_after_word(self, project_id: str) -> threading.Timer:
        """The wait after a word of *project_id*'s, started."""
        timer = threading.Timer(self.every_s(), self._wait_ends, args=(project_id,))
        timer.daemon = True
        timer.start()
        return timer

    def _wait_ends(self, project_id: str) -> None:
        """A change made during the wait is told now, and another wait
        starts; with none, the dataflow waits no more."""
        with self._lock:
            wait = self._waits.get(project_id)
            if wait is None:
                return
            if not wait.changed:
                del self._waits[project_id]
                return
            names, wait.names, wait.changed = wait.names, [], False
            wait.timer = self._wait_after_word(project_id)
            app = wait.app
        self._say(project_id, names, app)

    def _say(self, project_id: str, names: list, app) -> None:
        payload = {"projectId": project_id}
        if self.names is not None:
            payload[self.names] = names
        try:
            tell_editors(project_id, self.event, payload, app=app)
        except Exception:  # noqa: BLE001 - what changed stands whether or not the room heard of it
            log.exception("the room of dataflow %s could not be told %s", project_id, self.event)
