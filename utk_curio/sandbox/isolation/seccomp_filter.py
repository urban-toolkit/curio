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

#: Signals Python ignores when it starts. An ignored signal stays ignored
#: across ``exec``, so the wrapper puts them back to their defaults first, as
#: ``subprocess`` does in a child before it execs (``restore_signals``).
_IGNORED_BY_PYTHON = ("SIGPIPE", "SIGXFZ", "SIGXFSZ")


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


def exec_command(argv, *, required):
    """The command that runs *argv*, its first item a path, through this
    file's exec wrapper, which denies :data:`LEAVING_THE_GROUP` to it and to
    every process it starts. With *required*, a wrapper that cannot install
    the filter fails; without it, the wrapper then runs *argv* unfiltered."""
    return [
        sys.executable, "-P", os.path.abspath(__file__),
        *([REQUIRED] if required else []), "--", *argv,
    ]


def _deny_leaving_the_group():
    """Install the filter in this process. Whatever stops it is raised; a
    missing ``pyseccomp`` or libseccomp stops it before it changes anything."""
    import pyseccomp

    filter_ = denying(pyseccomp, LEAVING_THE_GROUP)
    set_no_new_privs()
    filter_.load()


def main(args):
    """The exec wrapper: ``[--required] -- <path> <arguments>``.

    It installs the filter, then execs *path* with *path* and *arguments* as
    its argv. When the filter cannot be installed, it fails with one line on
    stderr under ``--required``, and otherwise execs *path* without it,
    writing nothing: its stderr is the run's, which the run's user reads.
    """
    required = args[:1] == [REQUIRED]
    if required:
        args = args[1:]
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
