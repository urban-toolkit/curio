"""The seccomp filter code an isolated child and a JavaScript run share.

Both deny calls with EPERM through libseccomp (``pyseccomp``), on Linux, and
both set ``PR_SET_NO_NEW_PRIVS`` first, which lets an unprivileged process
install a filter and keeps a setuid program from gaining privilege. An
isolated Python child denies its whole denylist
(``child._install_seccomp_filter``). Node, on Linux, is denied the two calls
that leave a process group (:data:`LEAVING_THE_GROUP`), and so is every
process it starts: a filter is inherited across ``fork`` and ``exec``, and
nothing removes it.

Node gets its filter from this file run as an exec wrapper
(:func:`exec_command`): the sandbox is threaded, so it cannot run code of its
own between ``fork`` and ``exec`` (``preexec_fn``). Popen's
``start_new_session`` has already made the wrapper the leader of a session
and a process group of its own; the wrapper installs the filter and execs
Node, which keeps its pid, so Node leads them, and nothing it starts can
leave them.

Both drop to the execution account the same way too (:func:`drop_privileges`):
an isolated child after its filter, and the wrapper, when it is given the
account's ids, after Node's filter and before its exec. So under fork
isolation with an execution account, Node and every process it starts run as
the account an isolated child runs as, and where the drop fails, Node never
starts.

Both import ``pyseccomp`` through :func:`import_pyseccomp`, which finds libc
and libseccomp by soname, with neither ``ctypes.util`` nor a process: the
wrapper on every JavaScript run, and the zygote once, before its first fork,
so an isolated child finds it imported (``zygote._import_pyseccomp``).

The top level imports only the standard library, so the wrapper starts on it
and ``pyseccomp`` alone, wherever Curio is installed.
"""

import errno
import os
import signal
import sys

#: The calls that leave a process group: ``setsid``, for a session of its
#: own, and ``setpgid``, for another group (glibc's ``setpgrp`` is
#: ``setpgid(0, 0)``).
LEAVING_THE_GROUP = ("setsid", "setpgid")

#: The wrapper's flag for a run that must not start without its filter.
REQUIRED = "--required"

#: The wrapper's flag for the account a run drops to, ``--user UID:GID``.
USER = "--user"

#: Signals Python ignores when it starts. An ignored signal stays ignored
#: across ``exec``, so the wrapper puts them back to their defaults first, as
#: ``subprocess`` does in a child before it execs (``restore_signals``).
_IGNORED_BY_PYTHON = ("SIGPIPE", "SIGXFZ", "SIGXFSZ")

#: The libraries pyseccomp's import asks ``ctypes.util.find_library`` for, by
#: the name it asks with, and each one's soname on glibc: the C library, and
#: libseccomp 2, the major version pyseccomp binds.
_SONAMES = {"c": "libc.so.6", "seccomp": "libseccomp.so.2"}


def import_pyseccomp():
    """Import ``pyseccomp`` and return it, without ``ctypes.util``.

    pyseccomp's import finds libc and libseccomp with
    ``ctypes.util.find_library``. In a fresh interpreter, as the wrapper's
    is, importing ``ctypes.util`` imports shutil, subprocess and tempfile,
    and each ``find_library`` runs ``ldconfig -p`` in a subprocess: about
    10 of the 22 ms the import took on CI. So while pyseccomp imports here,
    ``ctypes.util`` is a stand-in whose ``find_library`` loads a library's
    soname with ``ctypes.CDLL``, as the import then does, and gives that
    name, the one ``ldconfig`` gives on glibc. The real ``ctypes.util``,
    imported then if it was not and kept, as the import would have kept it,
    answers the rest: a name the stand-in does not know, a soname that does
    not load (musl's C library is not ``libc.so.6``), and any other
    attribute of the stand-in (its module ``__getattr__``), so that a
    pyseccomp whose import reads more than ``find_library`` still imports.
    The ``ctypes.util`` there was before is put back as the import ends,
    whether it raised or not. That changes ``sys.modules`` for the import's
    length, so only a process in which no other thread runs Python calls
    this: the wrapper, the zygote as it warms up, and a child the zygote
    forked.

    A pyseccomp already imported is returned as it is, as the zygote's is in
    a child. Raises what the import raises: ImportError without pyseccomp,
    and pyseccomp's RuntimeError without libseccomp.
    """
    imported = sys.modules.get("pyseccomp")
    if imported is not None:
        return imported
    import ctypes
    import types

    real = sys.modules.get("ctypes.util")
    stand_in = types.ModuleType("ctypes.util")

    def the_real():
        nonlocal real
        if real is None:
            import importlib

            if sys.modules.get("ctypes.util") is stand_in:
                del sys.modules["ctypes.util"]
            real = importlib.import_module("ctypes.util")
        return real

    def find_library(name):
        soname = _SONAMES.get(name)
        if soname is not None:
            try:
                ctypes.CDLL(soname)
            except OSError:
                pass
            else:
                return soname
        return the_real().find_library(name)

    def real_attribute(name):
        return getattr(the_real(), name)

    stand_in.find_library = find_library
    stand_in.__getattr__ = real_attribute
    sys.modules["ctypes.util"] = stand_in
    ctypes.util = stand_in
    try:
        import pyseccomp
    finally:
        _put_back(sys.modules, "ctypes.util", stand_in, real)
        _put_back(vars(ctypes), "util", stand_in, real)
    return pyseccomp


def _put_back(names, name, stand_in, real):
    """Where *names* still holds *stand_in* at *name*, *real* again, or
    nothing when *real* is None."""
    if names.get(name) is stand_in:
        if real is None:
            del names[name]
        else:
            names[name] = real


def set_no_new_privs():
    """``prctl(PR_SET_NO_NEW_PRIVS, 1)``, which installing a filter needs.
    Raises OSError when the kernel refuses it."""
    import ctypes

    PR_SET_NO_NEW_PRIVS = 38
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(ctypes.get_errno())}")


def denying(seccomp, names):
    """A filter of the *seccomp* module that allows every call but *names*.

    Those fail with EPERM rather than killing the process, so the failure
    surfaces as an ordinary error (in Python a PermissionError) at the line
    that made the call, where a killed process would look like a crash. A name
    this architecture lacks has nothing to deny and is left out.
    """
    filter_ = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
    for name in names:
        try:
            filter_.add_rule(seccomp.ERRNO(errno.EPERM), name)
        except (ValueError, OSError):
            continue
    return filter_


def drop_privileges(uid, gid):
    """Become *uid* and *gid* for good, with no supplementary group: the
    isolated child's drop (``child._drop_privileges``), and the exec
    wrapper's, before it execs Node. An id that is None is not changed.

    Groups first: ``setgroups`` and ``setgid`` need the privilege that
    ``setuid`` gives away, so the uid first would leave the process in root's
    groups. Root's ``setgid`` and ``setuid`` set the real, effective and saved
    ids at once, and each of them is checked, with the group list. Raises
    OSError when the kernel refuses a call, or when one did not take.
    """
    if gid is not None:
        os.setgroups([])
        os.setgid(gid)
    if uid is not None:
        os.setuid(uid)
    took = (gid is None or (os.getresgid() == (gid,) * 3 and not os.getgroups())) and (
        uid is None or os.getresuid() == (uid,) * 3
    )
    if not took:
        raise OSError(
            f"the drop to uid {uid} and gid {gid} did not take: uids {os.getresuid()}, "
            f"gids {os.getresgid()}, groups {os.getgroups()}"
        )


def exec_command(argv, *, required, user=None):
    """The command that runs *argv*, its first item a path, through this
    file's exec wrapper, which denies :data:`LEAVING_THE_GROUP` to it and to
    every process it starts. With *required*, a wrapper that cannot install
    the filter fails; without it, the wrapper then runs *argv* unfiltered.
    With *user*, ``(uid, gid)``, the wrapper then drops to those ids as an
    isolated child does, and fails when it cannot, whatever *required* says."""
    return [
        sys.executable, "-P", os.path.abspath(__file__),
        *([REQUIRED] if required else []),
        *([USER, f"{user[0]}:{user[1]}"] if user is not None else []),
        "--", *argv,
    ]


def _deny_leaving_the_group():
    """Install the filter in this process. Whatever stops it is raised; a
    missing ``pyseccomp`` or libseccomp stops it before it changes anything."""
    filter_ = denying(import_pyseccomp(), LEAVING_THE_GROUP)
    set_no_new_privs()
    filter_.load()


def main(args):
    """The exec wrapper: ``[--required] [--user UID:GID] -- <path> <arguments>``.

    It installs the filter, then with ``--user`` drops to that uid and gid,
    the isolated child's order (``child.confine``), then execs *path* with
    *path* and *arguments* as its argv. When the filter cannot be installed,
    it fails with one line on stderr under ``--required``, and otherwise goes
    on without it, writing nothing: its stderr is the run's, which the run's
    user reads. When the drop fails, it fails with one line whatever
    ``--required`` says, so *path* never runs as the wrapper's own account in
    the execution account's place. It looks no account up: it is given the
    numbers.
    """
    required, user = False, None
    while args[:1] in ([REQUIRED], [USER]):
        if args[0] == REQUIRED:
            required, args = True, args[1:]
        else:
            user, args = (args[1] if len(args) > 1 else ""), args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    try:
        _deny_leaving_the_group()
    except Exception as exc:  # noqa: BLE001 - any failure means no filter
        if required:
            os.write(2, (
                f"Curio did not start {os.path.basename(args[0])}: it could not install the "
                f"seccomp filter that keeps every process a JavaScript node starts in the "
                f"node's process group ({type(exc).__name__}: {exc}). With "
                f"CURIO_ISOLATION=fork no JavaScript node runs without it.\n"
            ).encode("utf-8", "replace"))
            return 1
    if user is not None:
        try:
            uid, gid = (int(part) for part in user.split(":"))
            # Set with the filter; again here for a run whose filter was not
            # required and could not be installed.
            set_no_new_privs()
            drop_privileges(uid, gid)
        except Exception as exc:  # noqa: BLE001 - any failure means no drop
            os.write(2, (
                f"Curio did not start {os.path.basename(args[0])}: it could not drop to the "
                f"execution account's uid and gid {user} ({type(exc).__name__}: {exc}), and "
                f"a JavaScript node never runs as the sandbox's own account in its place.\n"
            ).encode("utf-8", "replace"))
            return 1
    for name in _IGNORED_BY_PYTHON:
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
    try:
        os.execv(args[0], args)
    except OSError as exc:
        os.write(2, f"Curio could not start {args[0]}: {exc}\n".encode("utf-8", "replace"))
        return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
