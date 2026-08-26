"""Top-level entry point for one isolated node execution.

NOT VERIFIED END TO END. The staging and child-logic halves are covered by
test_isolation_staging.py and test_isolation_child.py on every platform; the
fork, socket and confinement steps this module drives have never run. See
``docs/ARCHITECTURE.md`` for the current status.

The sequence, and why it is in this order:

1. Create a private scratch directory on the same filesystem as the artifact
   store, so staging can hardlink instead of copy.
2. Stage inputs and dataset files into it. This is the only point where the
   session-scoping check runs, and it runs here, in the parent.
3. Ask the zygote to fork a child. Wait, with a wall-clock deadline.
4. Read the child's manifest and validate it as hostile input.
5. Publish the dataset copy **before** persisting, because persisting moves the
   file out of the scratch directory.
6. Persist into DuckDB, then delete the scratch directory.

Failures at every step become ``stderr`` in the standard response shape, never
an exception and never a 500, matching what ``execute_code`` already promises
and what the frontend renders.
"""

import collections
import os
import threading

from utk_curio.sandbox.isolation import protocol, supervisor
from utk_curio.sandbox.isolation.protocol import ProtocolError
from utk_curio.sandbox.isolation.supervisor import IsolatedExecutionError

# Per-session import statements, the isolated counterpart of
# worker._session_imports. That one caches live module objects, which cannot
# cross a process boundary, so this keeps the source lines instead and the
# child replays them. Same LRU bound, same reasoning: there is no
# session-close signal to evict on.
_session_imports = collections.OrderedDict()
_MAX_IMPORT_SESSIONS = 32
_imports_lock = threading.Lock()


def _remember_imports(session_id, statements):
    if not statements:
        return
    key = session_id or ""
    with _imports_lock:
        existing = _session_imports.get(key)
        if existing is None:
            existing = []
            _session_imports[key] = existing
            while len(_session_imports) > _MAX_IMPORT_SESSIONS:
                _session_imports.popitem(last=False)
        for statement in statements:
            if statement not in existing:
                existing.append(statement)
        _session_imports.move_to_end(key)


def _imports_for(session_id):
    key = session_id or ""
    with _imports_lock:
        existing = _session_imports.get(key)
        if existing is None:
            return []
        _session_imports.move_to_end(key)
        return list(existing)


def reset_session_imports():
    """Test hook."""
    with _imports_lock:
        _session_imports.clear()


def _failure(stderr):
    """The standard response shape for a node that did not produce output."""
    return {"stdout": [], "stderr": stderr, "output": {"path": "", "dataType": "str"}}


def _persist_and_release(descriptor, *, node_type, session_id, save_dataset):
    """File the output away and drop the DuckDB write handle. Returns (id, dataset).

    Two things have to happen here that are easy to get wrong.

    **The write handle must be released.** DuckDB permits a single read-write
    connection across processes, and the backend opens short-lived read-only
    ones for the catalog, auto-install and output resolution. If the sandbox
    keeps the handle, those fail (see the note in ``worker.execute_code``'s
    finally block, and ``db._is_lock_conflict``). The in-process path releases
    per execution for exactly this reason; the isolated path has to as well, or
    the first isolated node starves the backend for the life of the process.

    **It must be serialized against ``/get``.** In the in-process path
    ``_exec_lock`` covers both the execution and this teardown, so a concurrent
    ``/get`` reading through the shared connection cannot have it closed
    underneath it (``chdir_locked`` takes the same lock). Isolated executions
    deliberately do not hold ``_exec_lock`` while the child runs, which is what
    makes them parallel, so it is taken here instead: just for the persist and
    the release, not for the execution. Concurrency where it matters is
    preserved, because the slow part is the child.
    """
    from utk_curio.sandbox.app.worker import _exec_lock
    from utk_curio.sandbox.util import staging
    from utk_curio.sandbox.util.db import release_connection

    with _exec_lock:
        try:
            # Before persist_output, which moves the file out of scratch.
            dataset_file = (
                staging.copy_output_dataset(descriptor) if save_dataset else None
            )
            art_id = staging.persist_output(
                descriptor, node_id=node_type, session_id=session_id
            )
        finally:
            release_connection()
    return art_id, dataset_file


def _parse_outputs_refs(file_path):
    """Return the list of refs a merge input names, or None if it names one.

    A merge output reaches a node in two shapes, both documented on
    ``worker._expand_outputs_wrapper``:

    * **live** -- a list literal of ``{'path': id}`` dicts, which is what the
      ``eval`` here was written for.
    * **reloaded** -- when the upstream merge output was persisted (a project
      save, or the JS-node round trip through DuckDB), the node receives a
      single bare ref to it instead.

    Evaluating the second shape parses an artifact id as a Python expression:
    ``1787698132616_820e772c`` is a decimal literal followed by a name, so it
    raised ``SyntaxError: invalid decimal literal`` and the node failed before
    running. Returning None says "this is one ref, not a list" and lets the
    caller load it the way the in-process path does.
    """
    text = (file_path or "").strip()
    if not text.startswith("["):
        return None
    # Empty builtins, the same guard execute_code uses.
    refs = eval(text, {"__builtins__": {}})  # noqa: S307
    return refs if isinstance(refs, list) else None


def _build_input_spec(file_path, data_type, scratch_dir, session_id):
    """Stage whatever this node's input references, returning its spec."""
    from utk_curio.sandbox.util import staging

    if data_type == "outputs":
        refs = _parse_outputs_refs(file_path)
        if refs is not None:
            return staging.stage_outputs_list(
                refs, scratch_dir, session_id=session_id
            )
        # The reloaded shape. What is stored under this id is the whole
        # ``{'dataType': 'outputs', 'data': [refs]}`` wrapper, so expand it to
        # the per-slot list user code expects -- staging it as a plain artifact
        # would hand the node the wrapper dict and break destructuring, which is
        # the same bug ``_expand_outputs_wrapper`` exists to prevent in-process.
        wrapper = staging.read_outputs_wrapper(file_path, session_id=session_id)
        if wrapper is not None:
            return staging.stage_outputs_list(
                wrapper, scratch_dir, session_id=session_id
            )
        # Tagged 'outputs' but holding something else. Stage it as it is rather
        # than failing: the in-process path is equally permissive here.
    if file_path:
        return staging.stage_input(
            file_path, scratch_dir, session_id=session_id, slot="in_0"
        )
    return dict(protocol.INPUT_NONE)


def execute_isolated(
    code,
    file_path,
    node_type,
    data_type,
    launch_dir=None,
    *,
    session_id=None,
    save_dataset=True,
    dataset_paths=None,
    user_key=None,
    config,
):
    """Run one node in an isolated child. Returns the standard response dict.

    *config* is an :class:`IsolationConfig`, carrying the socket path, limits
    and execution uid resolved once at startup.

    *launch_dir* is the fallback working directory, matching the in-process
    path's ``cwd``. Positional and third-from-last so this signature lines up
    with ``worker.execute_code``, which the caller picks between.

    *user_key* switches the child into that user's own work directory instead:
    persistent, writable, owned by the execution user, and the one place an
    isolated node may write. Isolated mode only -- in-process execution shares
    the sandbox's privileges anyway, so confining its cwd would buy nothing and
    would change behaviour for every existing dataflow.
    """
    from utk_curio.sandbox.util import staging
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    work_dir = launch_dir
    if user_key:
        work_dir = supervisor.prepare_user_work_dir(
            supervisor.user_work_dir(str(_shared_data_dir()), user_key),
            exec_uid=config.exec_uid,
            launch_dir=launch_dir,
        )

    scratch_dir = None
    try:
        scratch_dir = supervisor.make_scratch_dir(
            str(_shared_data_dir()), exec_uid=config.exec_uid
        )
    except OSError as exc:
        return _failure(f"Could not create a scratch directory for this node: {exc}")

    try:
        try:
            input_spec = _build_input_spec(
                file_path, data_type, scratch_dir, session_id
            )
        except KeyError as exc:
            # Matches load_from_duckdb: a missing or foreign artifact.
            return _failure(f"This node's input could not be loaded: {exc}")

        staged_datasets = staging.stage_dataset_paths(
            dataset_paths or {}, scratch_dir
        )

        request = protocol.build_exec_request(
            code=code,
            node_type=node_type,
            data_type=data_type,
            scratch_dir=scratch_dir,
            input_spec=input_spec,
            work_dir=work_dir,
            dataset_paths=staged_datasets,
            session_imports=_imports_for(session_id),
            limits=config.limits,
            wall_timeout=config.wall_timeout,
        )

        client = supervisor.ZygoteClient(config.socket_path)
        with config.slot():
            exit_code, signal_number, timed_out = client.run(
                request, wall_timeout=config.wall_timeout
            )

        if timed_out or exit_code not in (0, None) or signal_number is not None:
            return _failure(
                supervisor.describe_child_death(
                    exit_code, signal_number, timed_out,
                    wall_timeout=config.wall_timeout, limits=config.limits,
                )
            )

        manifest = supervisor.read_child_manifest(scratch_dir)

        if not manifest["ok"]:
            return {
                "stdout": manifest["stdout"],
                "stderr": manifest["stderr"],
                "output": {"path": "", "dataType": "str"},
            }

        _remember_imports(session_id, manifest["imports"])

        descriptor = manifest["output"]
        art_id, dataset_file = _persist_and_release(
            descriptor, node_type=node_type, session_id=session_id,
            save_dataset=save_dataset,
        )

        output = {"path": art_id, "dataType": descriptor["kind"]}
        if dataset_file:
            output["dataset"] = dataset_file
        return {
            "stdout": manifest["stdout"],
            "stderr": manifest["stderr"],
            "output": output,
        }

    except ProtocolError as exc:
        # The child sent something the parent will not act on. Worth naming as
        # such rather than as a generic failure: it means either a bug in the
        # child, or node code that tried to steer the parent.
        return _failure(
            f"The isolated execution returned a result the sandbox refused: {exc}"
        )
    except IsolatedExecutionError as exc:
        return _failure(f"Isolated execution failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - must never surface as a 500
        import traceback

        return _failure(
            f"Isolated execution failed unexpectedly: {exc}\n{traceback.format_exc()}"
        )
    finally:
        if scratch_dir:
            supervisor.cleanup_scratch(scratch_dir)


class IsolationConfig:
    """Everything resolved once at sandbox startup for the isolated path."""

    def __init__(self, *, socket_path, limits, wall_timeout, exec_uid=None,
                 parallelism=2):
        self.socket_path = socket_path
        self.limits = limits
        self.wall_timeout = wall_timeout
        self.exec_uid = exec_uid
        # Bounds concurrent children. The real memory ceiling is
        # parallelism * limits['memory_mb'], which is why this is small by
        # default and documented alongside --exec-memory-mb.
        self._semaphore = threading.BoundedSemaphore(max(1, parallelism))
        self.parallelism = max(1, parallelism)

    def slot(self):
        """Context manager bounding how many children run at once."""
        return _Slot(self._semaphore)

    @classmethod
    def from_environment(cls, env=None):
        env = env if env is not None else os.environ

        def _int(name, default):
            try:
                return int(env.get(name, default))
            except (TypeError, ValueError):
                return default

        limits = dict(supervisor.DEFAULT_LIMITS)
        limits["memory_mb"] = _int("CURIO_EXEC_MEMORY_MB", limits["memory_mb"])
        wall_timeout = _int(
            "CURIO_EXEC_TIMEOUT", supervisor.DEFAULT_WALL_TIMEOUT_SECONDS
        )
        # CPU time tracks the wall allowance: a node allowed 300s of wall time
        # should not be killed at 60s of CPU, and vice versa.
        limits["cpu_seconds"] = wall_timeout

        return cls(
            socket_path=env.get("CURIO_EXEC_SOCKET")
            or os.path.join(
                env.get("CURIO_LAUNCH_CWD", os.getcwd()),
                ".curio", "exec-zygote.sock",
            ),
            limits=limits,
            wall_timeout=wall_timeout,
            exec_uid=_resolve_exec_uid(env.get("CURIO_EXEC_USER")),
            parallelism=_int("CURIO_EXEC_PARALLELISM", 2),
        )


class _Slot:
    def __init__(self, semaphore):
        self._semaphore = semaphore

    def __enter__(self):
        self._semaphore.acquire()
        return self

    def __exit__(self, *_exc):
        self._semaphore.release()
        return False


def _resolve_exec_uid(user):
    """uid for the configured execution user, or None when not applicable."""
    if not user:
        return None
    try:
        import pwd

        return pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None
