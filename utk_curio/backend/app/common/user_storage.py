"""Where one user's own files live on disk.

Every per-user store — packages, agents, datasets, projects, and the small JSON
markers beside them — hangs off a single root. This module owns that root so
there is one answer rather than four copies of it: ``packages/storage.py``,
``datasets/infrastructure/storage.py`` and ``projects/storage.py`` each carried
an identical ``_launch_dir`` / ``_users_base`` / ``_user_key_segment`` trio, and
they all re-export from here now.

**The test rig gets its own tree.** ``CURIO_TESTING`` already moves the database
to ``.curio/test/`` (``backend/config.py::_resolve_database_uri``); this moves
the per-user files with it. Both halves are needed, because the two are keyed to
each other: the store path contains ``user.id``, and the e2e harness truncates
the ``user`` table between tests, so SQLite reissues low ids. Leave the files
where they are and a brand-new account silently inherits the previous occupant's
imported agents, installed packages, datasets and projects.

That is not hypothetical. It produced four separate failures during the
#186–#203 follow-ups, each of which read as a product bug first:

* an agent card offering a disabled control in one run and not the next,
* a dataset test failing because the account already held the row it meant to
  add,
* a package e2e inheriting a file an earlier run had deliberately damaged,
* and a marker file claiming examples were already seeded for an account that
  had never existed.

The same flag also stops a test run writing into the tree a developer's own
``curio.py start`` uses, which it previously shared.
"""
from __future__ import annotations

import os
from pathlib import Path

#: The shared read-only account. Not a numeric id, so it needs naming here.
GUEST_KEY = "guest"


def launch_dir() -> Path:
    """The directory Curio was started from, or the CWD."""
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def curio_root() -> Path:
    """``.curio/``, or ``.curio/test/`` when this process is a test rig.

    Read at call time rather than at import, so a test can flip the flag and so
    the launcher's value is honoured however late it is set — the same
    convention ``_resolve_database_uri`` and ``ensure_user_examples_seeded``
    already follow.
    """
    from utk_curio.backend.config import _is_testing

    # CURIO_STATE_DIR relocates the whole ``.curio`` tree without moving the
    # DATA root (``launch_dir`` also anchors ``/file/`` and relative node paths,
    # and ``safe_paths.is_within`` resolves symlinks, so those cannot be
    # redirected). The parallel e2e harness gives each backend+sandbox pair
    # its own; see backend/tests/shards.py.
    override = os.environ.get("CURIO_STATE_DIR")
    root = Path(override) if override else launch_dir() / ".curio"
    return root / "test" if _is_testing() else root


def users_base() -> Path:
    """``…/.curio[/test]/users`` — the parent of every per-user store."""
    return (curio_root() / "users").resolve()


def user_key_segment(user_key: str) -> str:
    """One path segment for *user_key*, or raise.

    Only a numeric id or the guest key may name a directory; anything else is a
    caller passing a username where an id belongs, which would put arbitrary
    text into a filesystem path.
    """
    if user_key == GUEST_KEY or user_key.isdigit():
        return user_key
    raise ValueError(f"Invalid user key for storage: {user_key!r}")


def clear_test_stores() -> list[str]:
    """Delete the per-user trees under a TEST root, and say what was removed.

    Emptying the ``user`` table and leaving ``.curio/test/users/`` behind is not
    a clean slate, it is a trap: the store path contains ``user.id``, SQLite
    reissues ids from 1 after a delete, and so the next account a test creates
    opens onto the previous one's imported agents, installed packages, datasets
    and projects. That is the header of this module, and it produced four
    separate failures in the #186-#203 follow-ups.

    Both resets call this: ``/api/testing/reset-db`` (over HTTP, when the
    backend owns a DB file the test process cannot resolve) and the e2e
    harness's own truncate path, which used to clear SQL only (#308).

    Refuses to touch anything outside ``.curio/test/``: without
    ``CURIO_TESTING`` the root is a developer's real store.
    """
    import logging
    import shutil

    from utk_curio.backend.app.common.safe_paths import is_within

    log = logging.getLogger(__name__)
    root = curio_root().resolve()
    if root.name != "test":
        log.warning("refusing to clear stores: %s is not a test root", root)
        return []

    cleared = []
    # The published-agents catalog hangs off the same root (agents/publications.py)
    # and leaks the same way.
    for target in (users_base(), (root / "agents-catalog").resolve()):
        if not is_within(target, root):  # pragma: no cover - both are children
            continue
        if not target.exists():
            continue
        shutil.rmtree(target, ignore_errors=True)
        cleared.append(target.name)
    return cleared
