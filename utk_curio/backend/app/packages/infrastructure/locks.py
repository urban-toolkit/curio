"""The per-user package-store lock contract (memo dev/99).

ONE owner of the lock file name and namespace, so the seeder and the readers
cannot drift apart: `seed.py` writes under this lock, and every reader that
forms a logical snapshot of the store reads under the same one.

Why readers need it at all: replacing a package cannot be a single atomic
rename, because POSIX will not rename a directory over a non-empty one. The
seeder therefore moves the old tree aside and then moves the staged tree into
place (`seed._swap_in_package`), and between those two renames the package
path does not exist. dev/93 removed the *partial* tree — a reader can never
see a half-copied package — but a reader overlapping that interval still sees
a healthy package as momentarily missing, which downstream becomes a false
template-resolution refusal, an incomplete roster, or a brief wrong installed
state. Sharing the lock closes it: a reader observes either the complete old
tree or the complete new one.

A writer — the seeder's swap, an install, an uninstall, a metadata edit, the
e2e plant — holds it **exclusive**: no reader and no other writer while it
changes the store. Readers hold it **shared** (``shared=True``): any number
of them at once, never with a writer, and a writer that waits keeps new
readers out (:mod:`common.file_locks`). A dataflow's agents read its owner's
store many times per turn, so with an exclusive lock a room's turns read it
one at a time.

The lock is **per-user** (one user's reseed never delays another's reads),
thread- and process-safe via :mod:`common.file_locks`, and **NOT reentrant**:
acquiring it twice on one thread deadlocks, shared or not. That is why
composite readers must call the private unlocked cores rather than the public
readers.
"""

from __future__ import annotations

from contextlib import contextmanager

from utk_curio.backend.app.common.file_locks import exclusive_lock, shared_lock
from utk_curio.backend.app.packages.repositories.store import user_packages_dir

# The seeder's own lock file, kept here so both sides name it in one place.
SEED_LOCK_FILENAME = ".seed.lock"
SEED_LOCK_NAMESPACE = "package-seed"


@contextmanager
def package_seed_lock(user_key: str, *, shared: bool = False):
    """Hold the per-user package-store lock: exclusive for a writer, shared
    with other readers for a reader (*shared*).

    The package-store directory is created if absent: the lock file has to
    live somewhere, and a first read for a user whose store does not exist yet
    must still serialize against the seeder that is about to create it. This
    does not change any caller's logical result — an empty store still yields
    an empty listing.

    Hold this only for bounded, local snapshot work: enumerate, read the
    manifests and assets the return value needs, detach the data, release.
    Never hold it across provider calls, network access, dependency
    installation, subprocess execution, package-backend invocation, or project
    writes, and never acquire another store lock underneath it — it is a leaf.
    """
    base = user_packages_dir(user_key)
    base.mkdir(parents=True, exist_ok=True)
    hold = shared_lock if shared else exclusive_lock
    with hold(
        base / SEED_LOCK_FILENAME,
        namespace=SEED_LOCK_NAMESPACE,
        key=user_key,
    ):
        yield
