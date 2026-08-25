"""What runs inside a forked child, before and around the user's node code.

NOT VERIFIED ON ANY MACHINE. This module needs Linux (fork, setrlimit, prctl,
seccomp) and has never been executed: it was written on a Windows host with no
container runtime available. Treat every claim below as intent, not as tested
behaviour, until it has run under `pytest utk_curio/sandbox/tests/test_isolation_*`
on Linux.

Order is the whole game here. Each step gives up a capability, and once given
up it cannot be taken back, so anything that needs a capability must happen
before the step that drops it:

1. ``setsid``          the child leads its own process group, so the parent can
                       kill the child *and anything it spawned* with one
                       ``killpg``. Must precede running user code, or a
                       runaway grandchild survives the timeout.
2. ``PR_SET_NO_NEW_PRIVS``  no ``setuid`` binary can regain privilege later.
                       Must precede the seccomp filter, and is what makes the
                       filter irrevocable.
3. seccomp             blocks the syscall groups the child has no business
                       using: sockets, ptrace, mount. Irrevocable once
                       installed.
4. ``setgid``/``setuid``    drop to the unprivileged execution user. Groups must
                       be dropped *before* the uid, or the process keeps its
                       supplementary groups forever.
5. ``setrlimit``       memory, CPU, processes, file size. Applied after the uid
                       drop so the child cannot raise its own soft limits back
                       to the (higher) hard limits.
6. close inherited fds  the parent's DuckDB handle and listening sockets are in
                       this process's table until we close them.
7. ``chdir``           into the scratch directory, the only place the child can
                       write.

Only then is user code compiled and run. The result goes to a file in the
scratch directory (not a pipe) so a child that dies mid-write cannot wedge the
parent on a half-read stream; the parent reads the file after the child exits.
"""

import json
import os
import sys

RESULT_FILENAME = "result.json"

# Kept in step with protocol.MAX_* so a child never writes a manifest the
# parent will reject wholesale for being oversized.
_MAX_STDOUT_LINES = 5_000
_MAX_STDOUT_LINE_CHARS = 2_000
_MAX_STDERR_CHARS = 256 << 10


class ChildSetupError(RuntimeError):
    """A confinement step failed. The child must die rather than run user code."""


# ---------------------------------------------------------------------------
# Confinement
# ---------------------------------------------------------------------------

def _set_no_new_privs():
    """prctl(PR_SET_NO_NEW_PRIVS, 1). Required before installing seccomp."""
    import ctypes

    PR_SET_NO_NEW_PRIVS = 38
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise ChildSetupError(
            f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(ctypes.get_errno())}"
        )


def _install_seccomp_filter(*, required):
    """Deny the syscall groups node code has no legitimate use for.

    A denylist, not an allowlist. An allowlist for arbitrary Python (which
    imports C extensions that use whatever they like) would break constantly
    and get widened until it meant nothing. The denylist is narrower in what it
    promises but is honest about it: it stops network egress, debugger
    attachment, and mount games, and it does not claim to be a full sandbox.

    Network denial is why hosting requires Linux. ``unshare(CLONE_NEWNET)``
    would be stronger but needs CAP_SYS_ADMIN, which Docker does not grant by
    default. Blocking ``socket`` outright is available to an unprivileged
    process and is enough: the child's result travels through a file, so it
    needs no sockets at all.
    """
    try:
        import pyseccomp as seccomp
    except ImportError as exc:
        if required:
            raise ChildSetupError(
                "pyseccomp is not installed, so the child cannot be prevented "
                "from opening sockets. Install it (pip install pyseccomp) or "
                "run with --isolation=off."
            ) from exc
        return False

    DENIED = (
        # Network. Without these the child can exfiltrate anything it reads.
        "socket", "socketcall", "connect", "bind", "listen", "accept", "accept4",
        "sendto", "sendmsg", "recvfrom", "recvmsg",
        # Debugger attachment: ptrace on a sibling would sidestep everything.
        "ptrace", "process_vm_readv", "process_vm_writev",
        # Namespace and mount games.
        "mount", "umount", "umount2", "unshare", "setns", "pivot_root", "chroot",
        # Kernel module loading.
        "init_module", "finit_module", "delete_module",
        # Raw kernel surfaces with a poor security history.
        "bpf", "perf_event_open", "userfaultfd", "kexec_load",
    )

    # EPERM rather than killing the process, so the failure surfaces as a
    # normal Python OSError with a traceback pointing at the user's line.
    # A killed child would just look like a mysterious crash.
    filter_ = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
    for name in DENIED:
        try:
            filter_.add_rule(seccomp.ERRNO(1), name)  # 1 == EPERM
        except (ValueError, OSError):
            # Syscall unknown on this architecture; nothing to block.
            continue
    filter_.load()
    return True


def _drop_privileges(uid, gid):
    """Become an unprivileged user. No-op when not running as root.

    Groups first: ``setgid`` and ``setgroups`` need the privilege that
    ``setuid`` gives away, so doing the uid first would strand the child in
    root's supplementary groups.
    """
    if os.getuid() != 0:
        # Already unprivileged, which is the normal case outside Docker. There
        # is nothing to drop, and asking would just fail.
        return False
    if gid is not None:
        os.setgroups([])
        os.setgid(gid)
    if uid is not None:
        os.setuid(uid)
        if os.getuid() != uid or os.geteuid() != uid:
            raise ChildSetupError("setuid did not take effect")
    return True


def _apply_rlimits(limits):
    """Cap memory, CPU, processes, file size, fds, and core dumps.

    ``RLIMIT_AS`` is what turns a runaway allocation into a ``MemoryError``
    inside the child instead of the kernel's OOM killer picking a victim, which
    on a busy host is as likely to be the backend as the offending child.
    """
    import resource

    def _set(what, value, name):
        if value is None:
            return
        try:
            resource.setrlimit(what, (value, value))
        except (ValueError, OSError) as exc:
            raise ChildSetupError(f"could not set {name}: {exc}") from exc

    memory_mb = limits.get("memory_mb")
    _set(resource.RLIMIT_AS, memory_mb * 1024 * 1024 if memory_mb else None,
         "RLIMIT_AS")

    cpu_seconds = limits.get("cpu_seconds")
    _set(resource.RLIMIT_CPU, cpu_seconds, "RLIMIT_CPU")

    _set(resource.RLIMIT_NPROC, limits.get("nproc"), "RLIMIT_NPROC")

    fsize_mb = limits.get("fsize_mb")
    _set(resource.RLIMIT_FSIZE, fsize_mb * 1024 * 1024 if fsize_mb else None,
         "RLIMIT_FSIZE")

    _set(resource.RLIMIT_NOFILE, limits.get("nofile"), "RLIMIT_NOFILE")

    # No core dumps: a dump of this process would contain the staged input data
    # and land somewhere the child does not control.
    _set(resource.RLIMIT_CORE, 0, "RLIMIT_CORE")


def _close_inherited_fds(keep):
    """Close every descriptor above stderr except those in *keep*.

    The fork inherited the parent's whole descriptor table, which includes the
    DuckDB write handle and the sandbox's listening socket. Leaving those open
    would hand the child exactly the access the scratch directory is meant to
    deny.
    """
    keep = set(keep) | {0, 1, 2}
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError:
        # No /proc. Fall back to the soft NOFILE limit, which is a superset of
        # what can be open.
        import resource
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        entries = [str(n) for n in range(min(soft, 65536))]

    for entry in entries:
        try:
            fd = int(entry)
        except ValueError:
            continue
        if fd in keep:
            continue
        try:
            os.close(fd)
        except OSError:
            pass


def confine(*, limits, uid=None, gid=None, scratch_dir, require_seccomp,
            keep_fds=()):
    """Apply every confinement step, in the order the module docstring sets out.

    Raises :class:`ChildSetupError` if any step fails. The caller must treat
    that as fatal for the child: running user code after a partial confinement
    is worse than not running it, because the operator would believe the
    boundary held.
    """
    os.setsid()
    _set_no_new_privs()
    seccomp_active = _install_seccomp_filter(required=require_seccomp)
    _drop_privileges(uid, gid)
    _apply_rlimits(limits)
    _close_inherited_fds(keep_fds)
    os.chdir(scratch_dir)
    return {"seccomp": seccomp_active}


# ---------------------------------------------------------------------------
# Rebuilding the node's input
# ---------------------------------------------------------------------------

def rebuild_input(spec, scratch_dir):
    """Turn a parent-authored input spec back into the object user code expects.

    The parent is trusted here (see the asymmetry note in ``protocol.py``), so
    this parses without validation. Reading happens from the scratch directory
    only, and every payload was staged there by the parent.
    """
    kind = spec.get("kind")

    if kind in ("none", None):
        return None
    if kind == "null":
        return None
    if kind in ("bool", "int", "float", "str"):
        return spec.get("value")

    if kind == "json":
        with open(os.path.join(scratch_dir, spec["file"]), encoding="utf-8") as handle:
            return json.load(handle)

    if kind == "dataframe":
        import pandas as pd
        from utk_curio.sandbox.util import codec

        frame = pd.read_parquet(os.path.join(scratch_dir, spec["file"]))
        return codec._restore_frame_from_parquet(
            frame, spec.get("encoded_object_columns") or []
        )

    if kind == "geodataframe":
        import geopandas as gpd
        from utk_curio.sandbox.util import codec

        frame = gpd.read_parquet(os.path.join(scratch_dir, spec["file"]))
        frame = codec._restore_frame_from_parquet(
            frame,
            spec.get("encoded_object_columns") or [],
            geometry_col=frame.geometry.name,
        )
        frame_metadata = spec.get("frame_metadata")
        if frame_metadata:
            frame.__dict__["metadata"] = frame_metadata
        return frame

    if kind == "raster":
        import rasterio

        return rasterio.open(os.path.join(scratch_dir, spec["file"]))

    if kind == "sequence":
        items = [rebuild_input(item, scratch_dir) for item in spec["items"]]
        return tuple(items) if spec.get("container") == "tuple" else items

    if kind == "mapping":
        return {
            key: rebuild_input(item, scratch_dir)
            for key, item in spec["items"].items()
        }

    raise ValueError(f"unknown input spec kind: {kind!r}")


# ---------------------------------------------------------------------------
# Serializing the node's output
# ---------------------------------------------------------------------------

def serialize_output(value, scratch_dir, *, slot="out"):
    """Write *value* into the scratch directory and describe it for the parent.

    Produces exactly the descriptor shape ``protocol.validate_payload``
    accepts. Filenames are flat by construction, because that is all the parent
    will accept.
    """
    from utk_curio.sandbox.util import codec

    kind = codec.detect_kind(value)

    if kind == "outputs":
        return {
            "kind": "outputs",
            "items": [
                serialize_output(item, scratch_dir, slot=f"{slot}_{index}")
                for index, item in enumerate(value)
            ],
        }

    if kind in ("null", "bool", "int", "float", "str"):
        # json.dumps in the manifest cannot carry NaN or Infinity as valid
        # JSON, so scrub here rather than letting the parent reject it.
        return {"kind": kind, "value": codec._json_safe_value(value)}

    if kind in ("list", "dict"):
        name = f"{slot}.json"
        with open(os.path.join(scratch_dir, name), "w", encoding="utf-8") as handle:
            json.dump(codec._json_safe_value(value), handle, ensure_ascii=False,
                      allow_nan=False)
        return {"kind": kind, "file": name}

    if kind == "geodataframe":
        name = f"{slot}.parquet"
        prepared, encoded = codec._prepare_frame_for_parquet(
            value, geometry_col=value.geometry.name
        )
        prepared.to_parquet(os.path.join(scratch_dir, name))
        meta = {"encoded_object_columns": encoded}
        frame_metadata = getattr(value, "metadata", None)
        if isinstance(frame_metadata, dict) and frame_metadata:
            meta["frame_metadata"] = frame_metadata
        return {"kind": kind, "file": name, "meta": meta}

    if kind == "dataframe":
        name = f"{slot}.parquet"
        prepared, encoded = codec._prepare_frame_for_parquet(value)
        codec._write_dataframe_parquet(prepared, os.path.join(scratch_dir, name))
        return {"kind": kind, "file": name,
                "meta": {"encoded_object_columns": encoded}}

    if kind == "raster":
        # Rasters are referenced by path. The child's raster already lives in
        # the scratch directory (either staged in or written there), so hand
        # the parent its flat name.
        name = os.path.basename(getattr(value, "name", "") or "")
        if not name:
            raise ValueError("raster output has no backing file")
        return {"kind": "raster", "file": name}

    raise ValueError(
        f"node returned {type(value).__name__}, which Curio cannot store"
    )


# ---------------------------------------------------------------------------
# Running the node
# ---------------------------------------------------------------------------

def _hoisted_import_statements(code):
    """Top-level import statements in *code*, as source lines.

    The in-process path caches live module objects for this
    (``worker._session_imports``); module objects cannot cross a process
    boundary, so the isolated path remembers the statements instead and replays
    them in the next child. Only top-level imports, matching
    ``worker._hoist_user_imports``: an import nested in ``try`` is conditional
    by intent and replaying it would turn a guarded optional dependency into a
    hard failure.
    """
    import ast
    import textwrap

    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        return []

    statements = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                statements.append(
                    f"import {alias.name}"
                    + (f" as {alias.asname}" if alias.asname else "")
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # A relative import in node code cannot resolve; skip it rather
                # than emitting a statement that always fails on replay.
                continue
            names = ", ".join(
                alias.name + (f" as {alias.asname}" if alias.asname else "")
                for alias in node.names
            )
            statements.append(f"from {node.module} import {names}")
    return statements


def run_node(request, namespace_factory):
    """Execute one node and return the manifest dict for the parent.

    *namespace_factory* returns the pre-seeded globals dict (the zygote's warm
    ``_globals_cache``), so this function stays testable without a fork.

    Never raises: every failure becomes ``ok: false`` plus a traceback in
    ``stderr``, because that is the contract the frontend renders and the
    in-process path already honours.
    """
    import contextlib
    import io
    import traceback

    scratch_dir = request["scratch_dir"]
    code = request["code"]

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    succeeded_imports = []
    output_descriptor = None
    ok = False

    try:
        with contextlib.redirect_stdout(captured_stdout), \
             contextlib.redirect_stderr(captured_stderr):
            namespace = namespace_factory()
            namespace["curio_dataset_path"] = _make_dataset_path_resolver(
                request.get("dataset_paths") or {}, scratch_dir
            )

            # Replay this session's earlier imports so an upstream node's
            # `import numpy as np` is visible here, matching the in-process
            # behaviour (#158). A statement that no longer resolves is skipped:
            # it was recorded because it once worked, and failing the whole
            # node for it would be a surprising regression.
            for statement in request.get("session_imports") or []:
                try:
                    exec(statement, namespace)
                except Exception:
                    continue

            # This node's own top-level imports, recorded for later nodes only
            # if they actually work here.
            for statement in _hoisted_import_statements(code):
                try:
                    exec(statement, namespace)
                    succeeded_imports.append(statement)
                except Exception:
                    continue

            exec(f"def userCode(arg):\n{code}", namespace)

            argument = rebuild_input(request.get("input") or {"kind": "none"},
                                     scratch_dir)

            # Same tripwire as the in-process path: code that mentions `arg`
            # with nothing wired upstream otherwise fails deep inside user code
            # with an unhelpful TypeError.
            if argument is None and "arg" in code:
                raise RuntimeError(
                    "This node's code refers to 'arg' but no input was "
                    "delivered. Check that an upstream node is connected and "
                    "has been run."
                )

            result = namespace["userCode"](argument)
            output_descriptor = serialize_output(result, scratch_dir)
            ok = True
    except BaseException:  # noqa: BLE001 - mirrors execute_code's catch-all
        captured_stderr.write(traceback.format_exc())

    stdout_lines = [
        line[:_MAX_STDOUT_LINE_CHARS]
        for line in captured_stdout.getvalue().split("\n") if line
    ][:_MAX_STDOUT_LINES]

    return {
        "ok": ok,
        "stdout": stdout_lines,
        "stderr": captured_stderr.getvalue()[:_MAX_STDERR_CHARS],
        "output": output_descriptor,
        "imports": succeeded_imports,
    }


def _make_dataset_path_resolver(staged, scratch_dir):
    """Rebuild ``curio_dataset_path`` over the staged copies.

    The in-process path injects a closure over absolute paths. Here the files
    were linked into the scratch directory, so the closure resolves to those
    instead; user code sees a working path either way.
    """
    mapping = dict(staged)

    def curio_dataset_path(dataset_id):
        name = mapping.get(str(dataset_id))
        if name is None:
            raise RuntimeError(
                f"Dataset '{dataset_id}' is not available in this environment - "
                "install it from the Data Catalog drawer."
            )
        return os.path.join(scratch_dir, name)

    return curio_dataset_path


def write_result(manifest, scratch_dir):
    """Write the manifest where the parent will look for it.

    A file rather than a pipe: a child killed on timeout leaves either no file
    or a partial one, and both are unambiguous to the parent. A half-written
    pipe would instead leave the parent blocking on a read that never
    completes.
    """
    path = os.path.join(scratch_dir, RESULT_FILENAME)
    temporary = path + ".partial"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, allow_nan=False)
    # Atomic rename, so the parent never observes a truncated manifest.
    os.replace(temporary, path)


def main(request, namespace_factory, *, uid=None, gid=None, require_seccomp=False):
    """Full child lifecycle: confine, run, write, exit. Never returns.

    Uses ``os._exit`` so no ``atexit`` handler inherited from the parent runs in
    the child. In particular the sandbox registers one that kills the whole
    process group (``sandbox/server.py::_kill_descendants``), which a normal
    exit here would fire against its siblings.
    """
    scratch_dir = request["scratch_dir"]
    try:
        confine(
            limits=request.get("limits") or {},
            uid=uid,
            gid=gid,
            scratch_dir=scratch_dir,
            require_seccomp=require_seccomp,
        )
    except BaseException:
        import traceback
        try:
            write_result(
                {"ok": False, "stdout": [], "stderr": traceback.format_exc(),
                 "output": None, "imports": []},
                scratch_dir,
            )
        except Exception:
            pass
        os._exit(3)

    try:
        manifest = run_node(request, namespace_factory)
        write_result(manifest, scratch_dir)
    except BaseException:
        os._exit(4)
    os._exit(0)
