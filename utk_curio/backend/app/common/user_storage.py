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

    root = launch_dir() / ".curio"
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
