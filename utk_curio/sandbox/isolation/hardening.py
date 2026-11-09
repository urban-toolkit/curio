"""Filesystem permissions that make the isolation boundary real.

Confining the child's syscalls is only half the job. If the artifact store and
the user database are world-readable, an isolated child can still open
``instance/urban_workflow.db`` with nothing more exotic than ``open()``: no
socket, no ptrace, no escape. seccomp does not help, because reading a file is
exactly what a data node legitimately does.

So this module answers one question: **can the execution user read the things it
must not?** (Three trees are asked the opposite, whether it could write them:
users' node libraries, :func:`audit_node_overlays`, Node's packages,
:func:`audit_node_packages`, and the model weights ``--model-weights-dir``
names, :func:`audit_model_weights`, which it must read.) It answers it in two
parts, split that way on purpose:

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

import contextlib
import glob
import os
import stat as stat_module
import sys

# Paths the execution user must not be able to read, relative to the launch
# directory. Each is (relative path, "why it matters") so a log line or a test
# failure explains itself. A ``*`` in a path stands for every folder there
# (``expand``).
SENSITIVE_PATHS = (
    ("instance", "the user database: password hashes and session tokens"),
    (".curio/data", "the artifact store: every session's data"),
    (".curio/users", "every user's imported datasets, projects and packages"),
    ("datasets", "the shared Data Catalog's published files"),
    ("packages/*/models", "a shipped model package's weights, staged into a child that runs one"),
    (".curio/fetched", "the catalog files a pip install downloaded, staged into a child that reads one"),
    (".env", "the deployment's keys and tokens"),
    (".curio/discovery", "the operator's source manifests: each names a folder or host the server reads"),
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
# under an execution user. (CI never saw it: the isolated job runs without one, so
# its children are root and root ignores mode bits.)
#
# So the *directory* is the control. At 0700 root-owned, nothing under it can
# be reached by path at all -- not by guessing an artifact id, not by listing.
# The files keep whatever mode they had, which is exactly what the hardlink
# needs. Copying instead of linking would allow per-copy permissions, at the
# cost of duplicating a multi-gigabyte raster for every node run.
HARDLINK_SOURCES = frozenset({
    ".curio/data", ".curio/users", "datasets", "packages/*/models", ".curio/fetched",
})

# What we want each of those to be. Owner-only: no read, no list, no traverse.
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

# Node's packages, the opposite case: a JavaScript node imports them as the
# execution user, so it must read them, and must never write them, where a
# module it changed or added would run in every later JavaScript run, and in
# the backend's own Node, which runs as root. A pip install keeps them in
# ``.curio/nodejs`` (relative to the launch directory); the sandbox's
# ``node_modules`` joins it wherever it is (:func:`node_package_trees`).
NODE_PACKAGES = (".curio/nodejs",)


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
            "regardless of permissions. Set CURIO_EXEC_USER to an "
            "unprivileged account."
        )
    if can_access(path_stat, uid=uid, gid=gid):
        return (
            f"the execution user can read {path} ({reason}). Node code would be "
            f"able to open it directly. Mode is "
            f"{stat_module.filemode(path_stat.st_mode)}."
        )
    return None


def expand(launch_dir, relative):
    """The paths *relative* names under *launch_dir*, relative to it: itself,
    or for a pattern with a ``*`` every existing folder it matches, sorted."""
    if "*" not in relative:
        return [relative]
    matches = glob.glob(os.path.join(glob.escape(str(launch_dir)), relative))
    return sorted(
        os.path.relpath(match, launch_dir).replace(os.sep, "/")
        for match in matches if os.path.isdir(match)
    )


def audit(launch_dir, *, uid, gid, paths=SENSITIVE_PATHS):
    """Report every sensitive path the execution user can still read.

    Returns a list of sentences, empty when nothing is exposed. Missing paths
    are skipped rather than reported: a fresh workspace has no ``instance/``
    yet, and warning about a directory that does not exist would be noise.
    """
    findings = []
    for pattern, reason in paths:
        for relative in expand(launch_dir, pattern):
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
    for pattern, _reason in paths:
        for relative in expand(launch_dir, pattern):
            target = os.path.join(launch_dir, relative)
            if not os.path.exists(target):
                continue
            if os.path.isdir(target):
                (changed if _tighten(target, DIRECTORY_MODE) else failed).append(relative)
                # Tightening the contents of a hardlink source would tighten the
                # staged copies the child must read; the 0700 above already makes
                # everything under it unreachable by path. See HARDLINK_SOURCES.
                if recurse_files and pattern not in HARDLINK_SOURCES:
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
    with contextlib.suppress(OSError):
        os.chmod(root, 0o711)
        if exec_uid is not None and os.getuid() == 0:
            os.chown(root, 0, -1)
    return root


def audit_node_overlays(shared_data_dir, *, uid, gid):
    """Report every user's node-library tree the execution user could WRITE.

    The inverse of :func:`audit`, and deliberately so. Those paths are findings
    because node code can read them; this one has to be readable - it is on the
    child's ``sys.path``, and a user's nodes cannot import their own libraries
    otherwise. What must not happen is node code WRITING there: the tree is an
    import path, so a planted module would shadow a real one for that user's
    every subsequent execution.

    ``prepare_user_overlay_dir`` creates them 0755 and does not chown, so this
    only fires if something else made one, or an operator changed it by hand.
    """
    from utk_curio.sandbox.isolation import supervisor

    root = os.path.join(
        os.path.dirname(os.path.abspath(shared_data_dir)),
        supervisor.OVERLAY_SUBDIR, "users",
    )
    findings = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return findings
    for name in entries:
        target = os.path.join(root, name)
        try:
            path_stat = os.stat(target)
        except OSError:
            continue
        if not stat_module.S_ISDIR(path_stat.st_mode):
            continue
        if _could_write(path_stat, uid=uid, gid=gid):
            findings.append(
                f"the execution user can write {target}, which is on the "
                f"import path of that user's nodes. Node code could plant a "
                f"module there and shadow a real one on every later run. Mode "
                f"is {stat_module.filemode(path_stat.st_mode)}."
            )
    return findings


def _could_write(path_stat, *, uid, gid):
    """Whether *uid* or *gid* could write something with these stat results,
    by any of its three ways: as its owner, through its group, or as other."""
    return bool(path_stat.st_mode & stat_module.S_IWOTH) or (
        uid is not None and path_stat.st_uid == uid
        and bool(path_stat.st_mode & stat_module.S_IWUSR)
    ) or (
        gid is not None and path_stat.st_gid == gid
        and bool(path_stat.st_mode & stat_module.S_IWGRP)
    )


def node_package_trees(launch_dir):
    """The folders that hold Node's packages: each of :data:`NODE_PACKAGES`
    under *launch_dir*, and the sandbox's ``node_modules``
    (``node_runtime.node_modules_dir``), wherever it is. Each once: a folder
    inside another is the other's already."""
    from utk_curio.sandbox.util import node_runtime

    candidates = [os.path.join(launch_dir, relative) for relative in NODE_PACKAGES]
    candidates.append(str(node_runtime.node_modules_dir()))
    trees, kept = [], []
    for path in sorted(candidates, key=lambda candidate: len(os.path.realpath(candidate))):
        real = os.path.realpath(path)
        if any(real == other or real.startswith(other.rstrip(os.sep) + os.sep) for other in kept):
            continue
        kept.append(real)
        trees.append(path)
    return trees


def _tree(top):
    """Each folder and file of the tree at *top*, *top* first, with its
    ``lstat``. A link is left out and never followed: a chmod follows one, to
    wherever it leads."""
    try:
        top_stat = os.lstat(top)
    except OSError:
        return
    if stat_module.S_ISLNK(top_stat.st_mode):
        return
    yield top, top_stat
    if not stat_module.S_ISDIR(top_stat.st_mode):
        return
    for root, directories, files in os.walk(top):
        for name in (*directories, *files):
            path = os.path.join(root, name)
            try:
                path_stat = os.lstat(path)
            except OSError:
                continue
            if not stat_module.S_ISLNK(path_stat.st_mode):
                yield path, path_stat


def _opened(mode, *, folder):
    """*mode* opened to read and closed to write: everyone reads a file, and
    reads and traverses a folder; a file that any class may execute every
    class may; group and other lose write. The owner's write stays."""
    if folder:
        mode |= 0o555
    else:
        mode |= 0o444 | (0o111 if mode & 0o111 else 0)
    return mode & ~0o022


def open_node_packages(launch_dir):
    """Make Node's packages (:func:`node_package_trees`) readable by the
    execution user and writable by no one but their owner. Returns what
    changed.

    Each folder and file changes only when its mode is not that already: a
    chmod in an image's layer copies the file up, and the image's
    ``node_modules`` is right as built. Best effort, as :func:`harden_paths`
    is: what stays writable is :func:`audit_node_packages`'s to report.
    """
    if not hasattr(os, "chmod") or sys.platform == "win32":
        return {"changed": [], "failed": [], "skipped": "not a POSIX host"}
    changed, failed = [], []
    for top in node_package_trees(launch_dir):
        for path, path_stat in _tree(top):
            mode = stat_module.S_IMODE(path_stat.st_mode)
            wanted = _opened(mode, folder=stat_module.S_ISDIR(path_stat.st_mode))
            if wanted != mode:
                (changed if _tighten(path, wanted) else failed).append(path)
    return {"changed": changed, "failed": failed, "skipped": None}


#: The most paths of one tree of Node's packages :func:`audit_node_packages`
#: names; past them it counts the rest.
MAX_NAMED_WRITABLE = 20


def audit_node_packages(launch_dir, *, uid, gid):
    """Report every folder and file of Node's packages the execution user
    could WRITE: a folder, where node code would add a module, or a file,
    where it would change one. The inverse of :func:`audit`, as
    :func:`audit_node_overlays` is: these must stay readable. A finding names
    a path under *launch_dir* relative to it, and a tree's findings past
    :data:`MAX_NAMED_WRITABLE` are one count."""

    def shown(path):
        relative = os.path.relpath(path, launch_dir)
        return path if relative.split(os.sep)[0] == os.pardir else relative

    findings = []
    for top in node_package_trees(launch_dir):
        writable = [(path, path_stat) for path, path_stat in _tree(top) if _could_write(path_stat, uid=uid, gid=gid)]
        for path, path_stat in writable[:MAX_NAMED_WRITABLE]:
            findings.append(
                f"the execution user can write {shown(path)}, one of Node's packages, so node code "
                f"could change a module every later JavaScript run imports. Mode is "
                f"{stat_module.filemode(path_stat.st_mode)}."
            )
        if len(writable) > MAX_NAMED_WRITABLE:
            findings.append(
                f"the execution user can write {len(writable) - MAX_NAMED_WRITABLE} more of "
                f"Node's packages under {shown(top)}."
            )
    return findings


def open_model_weights(weights_dir):
    """Make the model weights in *weights_dir*, the folder
    ``--model-weights-dir`` names, readable by the execution user and
    writable by no one but their owner, as :func:`open_node_packages` makes
    Node's packages. Returns what changed. Best effort: what stays writable is
    :func:`audit_model_weights`'s to report."""
    if not weights_dir or not hasattr(os, "chmod") or sys.platform == "win32":
        return {"changed": [], "failed": [], "skipped": "no folder, or not a POSIX host"}
    changed, failed = [], []
    for path, path_stat in _tree(weights_dir):
        mode = stat_module.S_IMODE(path_stat.st_mode)
        wanted = _opened(mode, folder=stat_module.S_ISDIR(path_stat.st_mode))
        if wanted != mode:
            (changed if _tighten(path, wanted) else failed).append(path)
    return {"changed": changed, "failed": failed, "skipped": None}


def audit_model_weights(weights_dir, *, uid, gid):
    """Report every folder and file of *weights_dir*, the folder
    ``--model-weights-dir`` names, the execution user could WRITE.

    The inverse of :func:`audit`, as :func:`audit_node_packages` is: isolated
    node code reads the weights there in place, so it must read them, and it
    must never write them, where a file it changed or added would be the
    model every account's later runs load. The server downloads them there
    (folders 0755, files 0644, its own); a link is neither followed nor
    reported. An execution user that is root is :func:`audit`'s finding.
    """
    if not weights_dir or uid is None or uid == 0:
        return []
    return [
        f"the execution user can write {path}, where isolated nodes read model weights in place: node "
        f"code could change a model every account runs. Mode is {stat_module.filemode(path_stat.st_mode)}."
        for path, path_stat in _tree(weights_dir) if _could_write(path_stat, uid=uid, gid=gid)
    ]


def apply_and_report(launch_dir, shared_data_dir, *, uid, gid, hosted, model_weights_dir=None):
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
            "No execution user is configured, so isolated node code runs as the "
            "same OS user as the sandbox and can read whatever the sandbox can, "
            "including the artifact store and the user database. Resource "
            "limits and syscall filtering still apply. Set CURIO_EXEC_USER "
            "to an unprivileged account for a filesystem boundary."
        ], hosted)

    # Order matters: harden first, then prepare. `harden_paths` skips the
    # scratch subtree, so this is belt and braces rather than the load-bearing
    # part -- but it means the scratch root gets its mode last either way, and
    # a future change to the walk cannot silently take it away again.
    harden_paths(launch_dir)
    open_node_packages(launch_dir)
    open_model_weights(model_weights_dir)
    prepare_scratch_root(shared_data_dir, exec_uid=uid)
    findings = audit(launch_dir, uid=uid, gid=gid)
    # #332: the node-library trees, Node's packages and the model weights
    # --model-weights-dir names must stay readable, so they are asked the
    # opposite question.
    findings += audit_node_overlays(shared_data_dir, uid=uid, gid=gid)
    findings += audit_node_packages(launch_dir, uid=uid, gid=gid)
    findings += audit_model_weights(model_weights_dir, uid=uid, gid=gid)
    return findings, bool(findings and hosted)
