"""A JavaScript run's Node is denied what an isolated Python child is, its network aside.

On Linux, Node starts through the exec wrapper of
``isolation/seccomp_filter.py``, whose filter is the isolated child's denylist
without its network calls (``seccomp_filter.NODE_CODE_DENIED``), and every
process Node starts inherits it. A program the wrapper runs, and one a
JavaScript node starts, gets EPERM from ``ptrace`` and ``process_vm_readv`` on
itself and from ``unshare``, and still makes a network socket. Without the
filter any process may make the first two calls, so they tell the filter is
there; Docker's default profile, where CI runs these, refuses ``unshare`` too.
"""

import importlib.util
import json
import subprocess
import sys

import pytest

from utk_curio.sandbox.tests import test_js_run_kills_at_return as kills

pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the seccomp filters exist only on Linux"),
    pytest.mark.skipif(importlib.util.find_spec("pyseccomp") is None, reason="pyseccomp is not installed"),
]

#: A program that prints, as JSON, what each call got: "allowed", or the name
#: of the error that refused it. ``ptrace(PTRACE_TRACEME)`` comes last: where
#: it is allowed, it makes the program's parent its tracer.
_TRIES_THE_DENIED_CALLS = r'''
import ctypes, errno, json, os, socket

libc = ctypes.CDLL(None, use_errno=True)


def outcome(result):
    return "allowed" if result != -1 else errno.errorcode.get(ctypes.get_errno(), str(ctypes.get_errno()))


class iovec(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("length", ctypes.c_size_t)]


source = ctypes.create_string_buffer(b"node code", 9)
target = ctypes.create_string_buffer(9)
local = iovec(ctypes.cast(target, ctypes.c_void_p), 9)
remote = iovec(ctypes.cast(source, ctypes.c_void_p), 9)
libc.process_vm_readv.restype = ctypes.c_ssize_t
seen = {
    "process_vm_readv": outcome(libc.process_vm_readv(os.getpid(), ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)),
    "unshare": outcome(libc.unshare(0x10000000)),
}
try:
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).close()
    seen["socket"] = "allowed"
except OSError as error:
    seen["socket"] = errno.errorcode.get(error.errno, str(error.errno))
seen["ptrace"] = outcome(libc.ptrace(0, 0, None, None))
print(json.dumps(seen, sort_keys=True))
'''

#: What the program must see under Node's filter.
DENIED_BUT_THE_NETWORK = {"process_vm_readv": "EPERM", "ptrace": "EPERM", "socket": "allowed", "unshare": "EPERM"}


def test_a_program_the_wrapper_runs_is_denied_what_an_isolated_child_is_but_the_network():
    """The wrapper installs the child's denylist without its network calls,
    then execs: the program it runs cannot attach to a process or read
    another's memory, nor make namespaces, and keeps its network."""
    from utk_curio.sandbox.isolation import seccomp_filter

    command = seccomp_filter.exec_command(
        [sys.executable, "-I", "-S", "-c", _TRIES_THE_DENIED_CALLS], required=True,
    )
    done = subprocess.run(command, capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, f"the wrapper, or the program it execs, failed: {done.stderr}"
    assert json.loads(done.stdout) == DENIED_BUT_THE_NETWORK, (
        f"the program the wrapper execs was not denied what an isolated child is, or lost its network: {done.stdout}"
    )


def test_a_process_a_javascript_node_starts_is_denied_them_too(tmp_path):
    """Node passes its filter to every process it starts: a program a
    JavaScript node runs is denied the same calls, and keeps its network."""
    code = (
        "const { spawnSync } = await import('node:child_process');\n"
        f"const done = spawnSync({json.dumps(sys.executable)}, "
        f"['-I', '-S', '-c', {json.dumps(_TRIES_THE_DENIED_CALLS)}], {{ encoding: 'utf8' }});\n"
        "return { status: done.status, stdout: done.stdout, stderr: done.stderr };\n"
    )
    run = kills._Run(code, tmp_path, "TRIES_THE_DENIED_CALLS")
    assert run.ended_within(kills.WAIT), f"the run has not returned {kills.WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None, "\n".join(stderr)
    outcome = json.loads(result)
    assert outcome["success"], outcome
    started = outcome["value"]
    assert started["status"] == 0, f"the program the node started failed: {started['stderr']}"
    assert json.loads(started["stdout"]) == DENIED_BUT_THE_NETWORK, (
        f"a process a JavaScript node started was not denied what an isolated child is, or lost its network: "
        f"{started['stdout']}"
    )
