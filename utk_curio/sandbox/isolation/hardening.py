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
    (".curio/users", "every user's imported datasets, projects and packages"),
    ("datasets", "the shared Data Catalog's published files"),
    (".env", "the deployment's secrets, including SECRET_KEY"),
)

# Directories whose contents reach a child as a hardlink, and which therefore
# must NOT have their files tightened.
#
# The whole model turns on one Unix fact: reaching a file needs both a
# permitted mode *and* traversal of every directory on the path used to get
# there. A hardlink is a second path to the same inode -- and the inode's mode
# is shared, so a staged copy cannot be less permissive than its source.
#
# Tightening the files here therefore tightens the staged copy the child is
# meant to read. ``.curio/data/artifacts/<id>.parquet`` is hardlinked into the
# scratch directory by ``staging.stage_input``; at 0600 root-owned the child
# could not read its own input, and every dataframe node would have failed
# under an --exec-user. (CI never saw it: the isolated job runs without one, so
# its children are root and root ignores mode bits.)
#
# So the *directory* is the control. At 0700 root-owned, nothing under it can
# be reached by path at all -- not by guessing an artifact id, not by listing.
# The files keep whatever mode they had, which is exactly what the hardlink
# needs. Copying instead of linking would allow per-copy permissions, at the
# cost of duplicating a multi-gigabyte raster for every node run.
HARDLINK_SOURCES = frozenset({".curio/data", ".curio/users", "datasets"})

# What we want each of those to be. Owner-only: no read, no list, no traverse.
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


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

    changed, failed = [], []
    for relative, _reason in paths:
        target = os.path.join(launch_dir, relative)
        if not os.path.exists(target):
            continue
        if os.path.isdir(target):
            (changed if _tighten(target, DIRECTORY_MODE) else failed).append(relative)
            # Tightening the contents of a hardlink source would tighten the
            # staged copies the child must read; the 0700 above already makes
            # everything under it unreachable by path. See HARDLINK_SOURCES.
            if recurse_files and relative not in HARDLINK_SOURCES:
                for root, directories, files in os.walk(target):
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
    from utk_curio.sandbox.isolation.supervisor import scratch_root

    root = scratch_root(shared_data_dir)
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
