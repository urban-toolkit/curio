"""Who asked for an agent's run: the person whose request it serves.

A dataflow's agents work on its owner's storage, model and key, whoever drives
them: the owner, or an editor the owner invited (``projects/access.py``). Four
things follow the asker:

* the saved Node code keys a run lists and resolves (:func:`keys_account`), so
  an invited editor's run names only the editor's keys, never the owner's;
* who a change made for the request is by (:func:`account`), so Provenance
  names the person who asked;
* who wrote a chat message (:func:`writer`);
* the skills of the dataflow's packages a run holds (:func:`editor`): an
  editor's run holds those of the packages the owner added to the dataflow
  (``skill_runs.package_skills``).

A request's asker is its signed-in account (:func:`person`). A job's thread
holds no request, so a job takes its asker when it starts and hands it on, as
Solve does with its ``acting_user`` and the keys in its grounding base.
"""

from __future__ import annotations


def person():
    """The account the request acts as, or None outside a request."""
    try:
        from flask import g, has_request_context

        return getattr(g, "user", None) if has_request_context() else None
    except Exception:  # noqa: BLE001 - not under Flask
        return None


def _storage_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def keys_account(user_key: str, user=None) -> str:
    """The storage key whose saved Node code keys a run of the dataflow
    *user_key* stores lists and resolves: those of *user*, who asked for it,
    else the request's account. The dataflow's own *user_key* only when no
    one is known: a run outside a request that was handed no asker."""
    asker = user if user is not None else person()
    return _storage_key(asker) if asker is not None else user_key


def account(user_key: str, user=None) -> str:
    """Who a change made for the request to the dataflow *user_key* stores
    is by, as a change's :class:`~utk_curio.backend.app.collaboration.dataflow_docs.Actor`
    names its account: the person who asked, an editor the owner invited among
    them: *user*, the asker a job took when it started, else the request's
    account. The dataflow's own *user_key* for its owner, whose storage key it
    is, and when no one is known: a job's thread holds no request."""
    asker = user if user is not None else person()
    if asker is None or getattr(asker, "id", None) is None or _storage_key(asker) == user_key:
        return user_key
    return str(asker.id)


def editor(user_key: str, user=None) -> bool:
    """Whether a run on the dataflow *user_key* stores is for an editor its
    owner invited: *user*, the asker a job took when it started, else the
    request's account, is known and is not the owner, whose storage key
    *user_key* is. False when no one is known."""
    asker = user if user is not None else person()
    return asker is not None and getattr(asker, "id", None) is not None and _storage_key(asker) != user_key


def writer() -> dict | None:
    """The request's account as a chat message names its writer, the way a
    point of the history names a person; None outside a request."""
    asker = person()
    if asker is None or getattr(asker, "id", None) is None:
        return None
    from utk_curio.backend.app.projects.services import _history_person

    return _history_person(asker)
