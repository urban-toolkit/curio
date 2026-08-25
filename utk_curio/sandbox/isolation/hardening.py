"""Filesystem permissions that make the isolation boundary real.

Confining the child's syscalls is only half the job. If the artifact store and
the user database are world-readable, an isolated child can still open
``instance/urban_workflow.db`` with nothing more exotic than ``open()``: no
socket, no ptrace, no escape. seccomp does not help, because reading a file is
exactly what a data node legitimately does.

So this module answers one question: **can the execution user read the things it
must not?** It answers it in two parts, split that way on purpose:

``audit``
    Pure. Takes mode bits, owner and group, and decides whether a given uid/gid
    could read or write. No filesystem, no platform assumptions, so the logic is
    testable anywhere, including on Windows where none of this applies.

``harden_paths``
    Applies the tightening. POSIX only, and only when isolation is actually
    enabled: doing this unconditionally would break CI (which relies on the
    container being root with ``umask 000``) and the bind-mounted host
    directories the live deployments use, in service of a feature that is off by
    default.

A note on what this cannot fix. The child runs as the same uid as every other
child, so this is a boundary between *node code and the host*, not between two
Curio users' node code. Two users' nodes running concurrently can reach each
other's scratch directories only if the mode bits allow it, which is why scratch
directories are 0700 and owned by the execution user; but they are the same
user, so a determined node could still find a sibling's directory. Session
scoping in the parent is what keeps artifacts apart, and that is not something a
child can reach at all.
"""

import os
import stat as stat_module
import sys

# Paths the execution user must not be able to read, relative to the launch
# directory. Each is (relative path, "why it matters") so a log line or a test
# failure explains itself.
SENSITIVE_PATHS = (
    ("instance", "the user database: password hashes and session tokens"),
    (".curio/data", "the artifact store: every session's data"),
    (".env", "the deployment's secrets, including SECRET_KEY"),
)

# Why ``datasets/`` is deliberately absent, since it looks like it belongs:
# ``staging.stage_dataset_paths`` reaches a dataset file into a child's scratch
# directory with ``os.link``, and a hardlink shares the inode -- and therefore
# the mode -- with its source. Tightening ``datasets/`` to 0600 root-owned would
# tighten the staged copy the child is meant to read, breaking every
# ``curio_dataset_path`` call. The alternative is copying instead of linking,
# which that module avoids on purpose ("avoids duplicating a multi-gigabyte
# raster or parquet for every node run"). Denying it needs the staging design to
# change first; adding it here alone would just break dataset loading.

# What we want each of those to be. Owner-only, and directories need execute to
# be traversable by their owner.
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

# One of them cannot be owner-only, and getting this wrong breaks isolation
# completely rather than subtly.
#
# Every execution's scratch directory lives *inside* the artifact store
# (``supervisor.SCRATCH_SUBDIR`` under ``.curio/data``), and the child chdirs
# into it as the last step of ``child.confine``. At 0700 root-owned the child --
# which by then has dropped to the execution user -- cannot traverse the store
# to reach it, so `confine` fails and every isolated node dies before running a
# line of user code.
#
# 0711 grants exactly what is needed and nothing more: traverse, but no read and
# no list. The execution user cannot enumerate the store, and the files in it
# stay FILE_MODE (0600, root-owned), so guessing an artifact name still gets
# EACCES. ``describe_exposure`` agrees -- it asks about *read* access, which
# 0711 does not grant -- so the startup audit stays clean.
#
# ``test_isolation_linux.py::isolated_dropped`` has always had to do this by
# hand ("0711 up the chain: the child must traverse to its scratch dir without
# being able to list any level of it"), which is how this surfaced.
TRAVERSABLE_DIRECTORIES = frozenset({".curio/data"})
TRAVERSE_MODE = 0o711


def can_access(path_stat, *, uid, gid, write=False):
    """Could *uid*/*gid* read (or write) something with these stat results?

    Pure, so the whole truth table is testable without touching a filesystem
    or being on POSIX. ``path_stat`` needs ``st_mode``, ``st_uid`` and
    ``st_gid``; a real ``os.stat_result`` or any stand-in with those works.

    Note root is not special-cased: root can read anything regardless of mode
    bits, and pretending otherwise would make this function lie. Callers that
    care ask :func:`describe_exposure` instead, which is explicit about it.
    """
    mode = path_stat.st_mode
    if write:
        owner, group, other = stat_module.S_IWUSR, stat_module.S_IWGRP, stat_module.S_IWOTH
    else:
        owner, group, other = stat_module.S_IRUSR, stat_module.S_IRGRP, stat_module.S_IROTH

    if path_stat.st_uid == uid:
        return bool(mode & owner)
    if path_stat.st_gid == gid:
        return bool(mode & group)
    return bool(mode & other)


def describe_exposure(path, path_stat, *, uid, gid, reason):
    """Return a warning sentence when *uid* can read *path*, else None."""
    if uid == 0:
        return (
            f"the execution user is root, so it can read {path} ({reason}) "
            "regardless of permissions. Configure --exec-user with an "
            "unprivileged account."
        )
    if can_access(path_stat, uid=uid, gid=gid):
        return (
            f"the execution user can read {path} ({reason}). Node code would be "
            f"able to open it directly. Mode is "
            f"{stat_module.filemode(path_stat.st_mode)}."
        )
    return None


def audit(launch_dir, *, uid, gid, paths=SENSITIVE_PATHS):
    """Report every sensitive path the execution user can still read.

    Returns a list of sentences, empty when nothing is exposed. Missing paths
    are skipped rather than reported: a fresh workspace has no ``instance/``
    yet, and warning about a directory that does not exist would be noise.
    """
    findings = []
    for relative, reason in paths:
        target = os.path.join(launch_dir, relative)
        try:
            path_stat = os.stat(target)
        except OSError:
            continue
        finding = describe_exposure(
            relative, path_stat, uid=uid, gid=gid, reason=reason
        )
        if finding:
            findings.append(finding)
    return findings


def _tighten(target, mode):
    """chmod *target* to *mode*, returning True when it took effect."""
    try:
        os.chmod(target, mode)
        return True
    except OSError:
        return False


def harden_paths(launch_dir, *, paths=SENSITIVE_PATHS, recurse_files=True):
    """Restrict the sensitive paths to their owner. Returns what changed.

    Only called when isolation is enabled. Applying this on every launch would
    break the CI overlay (root plus ``umask 000``, with the host reaching into
    the bind mounts) and could lock a host user out of their own
    ``./instance`` directory, for no benefit when node code runs in-process
    anyway.

    Best effort: a chmod that fails is reported, not raised. The caller decides,
    and for a hosted instance :func:`audit` afterwards is what turns a failure
    into a refusal to serve.
    """
    if not hasattr(os, "chmod") or sys.platform == "win32":
        return {"changed": [], "failed": [], "skipped": "not a POSIX host"}

    from utk_curio.sandbox.isolation.supervisor import SCRATCH_SUBDIR

    changed, failed = [], []
    for relative, _reason in paths:
        target = os.path.join(launch_dir, relative)
        if not os.path.exists(target):
            continue
        if os.path.isdir(target):
            directory_mode = (
                TRAVERSE_MODE if relative in TRAVERSABLE_DIRECTORIES
                else DIRECTORY_MODE
            )
            (changed if _tighten(target, directory_mode) else failed).append(relative)
            if recurse_files:
                for root, directories, files in os.walk(target):
                    # The scratch tree belongs to the execution user, not to us.
                    # Walking into it would undo prepare_scratch_root's 0711 on
                    # the root, and would re-own any live execution's directory
                    # out from under the child currently running in it.
                    if SCRATCH_SUBDIR in directories:
                        directories.remove(SCRATCH_SUBDIR)
                    for name in directories:
                        _tighten(os.path.join(root, name), DIRECTORY_MODE)
                    for name in files:
                        _tighten(os.path.join(root, name), FILE_MODE)
        else:
            (changed if _tighten(target, FILE_MODE) else failed).append(relative)
    return {"changed": changed, "failed": failed, "skipped": None}


def prepare_scratch_root(shared_data_dir, *, exec_uid=None):
    """Create the scratch root and make it usable by the execution user.

    The per-execution directories inside are 0700 and owned by the execution
    user (see ``supervisor.make_scratch_dir``); this only has to let that user
    traverse into the root, hence 0711 rather than 0755. Nothing may *list* the
    root, so one execution cannot enumerate another's scratch directory by
    reading the parent.
    """
    from utk_curio.sandbox.isolation.supervisor import SCRATCH_SUBDIR

    root = os.path.join(shared_data_dir, SCRATCH_SUBDIR)
    os.makedirs(root, exist_ok=True)
    if sys.platform == "win32":
        return root
    try:
        os.chmod(root, 0o711)
        if exec_uid is not None and os.getuid() == 0:
            os.chown(root, 0, -1)
    except OSError:
        pass
    return root


def apply_and_report(launch_dir, shared_data_dir, *, uid, gid, hosted):
    """Harden, then audit, and say what is left. Returns (findings, fatal).

    *fatal* is True when a hosted instance is still exposed after hardening.
    The caller refuses to serve in that case: a hosted deployment that believes
    it is isolated while node code can read every password hash is worse than
    one that never started, because nobody would know.
    """
    if uid is None:
        # No execution user configured, so the child runs as the sandbox's own
        # user and shares all its access. Isolation still bounds resources and
        # syscalls, but not the filesystem, and that should be said plainly.
        return ([
            "No --exec-user is configured, so isolated node code runs as the "
            "same OS user as the sandbox and can read whatever the sandbox can, "
            "including the artifact store and the user database. Resource "
            "limits and syscall filtering still apply. Configure --exec-user "
            "with an unprivileged account for a filesystem boundary."
        ], hosted)

    # Order matters: harden first, then prepare. `harden_paths` skips the
    # scratch subtree, so this is belt and braces rather than the load-bearing
    # part -- but it means the scratch root gets its mode last either way, and
    # a future change to the walk cannot silently take it away again.
    harden_paths(launch_dir)
    prepare_scratch_root(shared_data_dir, exec_uid=uid)
    findings = audit(launch_dir, uid=uid, gid=gid)
    return findings, bool(findings and hosted)
