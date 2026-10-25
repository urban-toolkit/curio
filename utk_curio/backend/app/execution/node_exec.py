"""Running one node in the sandbox, the way Play does.

The body of the ``/processPythonCode`` and ``/processJavaScriptCode`` routes,
moved here so that a caller with no request (a run on a thread of its own)
runs a node exactly as the browser's Play does: the same dataset paths,
collections, connection keys and models, the same auto-install of the output,
the same runtime journal record and monitor counters. Every function takes the
account and the session token explicitly instead of reading them from the
request.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from utk_curio.backend.app.datasets.domain.code_refs import (
    MAX_DATASET_IDS as MAX_EXEC_DATASET_IDS,
    dataset_ids_in_code,
)
from utk_curio.backend.app.discovery.application.exec_collections import (
    resolve_exec_collections,
)
from utk_curio.backend.app.execution.sandbox_client import sandbox_request
from utk_curio.backend.app.monitor import counters as _monitor_counters
from utk_curio.backend.app.monitor import errors as _monitor_errors
from utk_curio.backend.config import CURIO_DEFAULT_SAVE_NODE_OUTPUT

# The sandbox round trip for one node run, in seconds. It was 120 historically;
# bumped so legitimate long-running nodes (large CSV loads, heavy spatial ops,
# GPU compute) don't hit the request library's deadline before the sandbox has
# had a chance to respond.
SANDBOX_EXEC_TIMEOUT = 600

# The route each language's runs were served by, kept as the log label.
_LABELS = {"python": "/processPythonCode", "javascript": "/processJavaScriptCode"}


@dataclass(frozen=True)
class NodeRun:
    """One node execution, as the browser's Play sends it."""

    code: str
    node_type: str
    node_id: str | None = None
    input: dict | None = None
    dataflow_id: str | None = None
    node_name: str | None = None
    save_output_dataset: bool = bool(CURIO_DEFAULT_SAVE_NODE_OUTPUT)
    # The wired circles, in circle order: the value on circle k is the code's
    # input_k (sandbox/util/input_names.py).
    input_slots: tuple[int, ...] | None = None

    @classmethod
    def from_request_json(cls, body: dict) -> "NodeRun":
        save_output_dataset = body.get('saveOutputDataset', CURIO_DEFAULT_SAVE_NODE_OUTPUT)
        if isinstance(save_output_dataset, str):
            save_output_dataset = save_output_dataset.strip().lower() not in ('0', 'false', 'no', 'off')
        return cls(
            code=body['code'],
            node_type=body['nodeType'],
            node_id=body.get('nodeId') or None,
            input=body.get('input'),
            dataflow_id=body.get('dataflowId') or None,
            node_name=body.get('nodeName') or None,
            save_output_dataset=bool(save_output_dataset),
            input_slots=parse_input_slots(body.get('inputSlots')),
        )


def parse_input_slots(raw) -> tuple[int, ...] | None:
    """A request's ``inputSlots``: the wired circles, or None when absent or malformed."""
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    try:
        slots = tuple(int(s) for s in raw)
    except (TypeError, ValueError):
        return None
    return slots if all(0 <= s <= 255 for s in slots) else None


def parse_input_ref(req_input: dict | None) -> dict:
    """Normalize the input reference field from execution requests."""
    result = {'path': '', 'dataType': ''}
    if not req_input:
        return result
    if req_input.get('dataType') == 'outputs' and 'data' in req_input:
        result['path'] = req_input['data']
        result['dataType'] = 'outputs'
    elif 'filename' in req_input:
        result['path'] = req_input['filename']
        result['dataType'] = req_input['dataType'] if req_input['dataType'] != 'outputs' else 'file'
    elif 'path' in req_input:
        result['path'] = req_input['path']
        result['dataType'] = req_input['dataType'] if req_input['dataType'] != 'outputs' else 'file'
    return result


#: The most of a run's inputs whose saved outputs are resolved for it.
MAX_SAVED_INPUTS = 64


def input_names(input_ref: dict) -> list[str]:
    """The output names a run's input ref reads: its one name, or, for a node
    with several inputs (``outputs``), each element's."""
    path = (input_ref or {}).get('path')
    if isinstance(path, str):
        return [path] if path else []
    names = []
    for elem in path if isinstance(path, (list, tuple)) else []:
        name = elem.get('path') if isinstance(elem, dict) else elem
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def resolve_saved_inputs(input_ref: dict, dataflow_id: str | None) -> dict:
    """``{name: {"path", "dataType"}}`` for each input this run reads that is
    a saved output of its dataflow: the file its owner's store holds
    (``projects/services.saved_output_of``). The sandbox reads it in place
    when its store has no row of that name for the run's session, as after a
    reopen under a new sign-in.

    Fail-open like dataset paths: a name that does not resolve reads as the
    store answers it. Nothing else holds a saved output, so a resolution that
    fails, or inputs past ``MAX_SAVED_INPUTS``, are said in the log, where the
    node's "No artifact with id" can be traced to them.
    """
    if not dataflow_id:
        return {}
    try:
        from utk_curio.backend.app.projects.services import saved_output_of

        names = input_names(input_ref)
        if len(names) > MAX_SAVED_INPUTS:
            print(
                f"[node_exec] a run names {len(names)} inputs; only the first "
                f"{MAX_SAVED_INPUTS} are read from their saved files",
                flush=True,
            )
        resolved = {}
        for name in names[:MAX_SAVED_INPUTS]:
            saved = saved_output_of(dataflow_id, name)
            if saved is not None:
                resolved[name] = {"path": str(saved.path), "dataType": saved.data_type or ""}
        return resolved
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[node_exec] saved input resolution failed: {e.__class__.__name__}", flush=True)
        return {}


def resolve_dataset_paths(code: str, dataflow_id: str | None, user, formats: dict | None = None) -> dict:
    """Resolve the dataset ids referenced by *code* to absolute file paths.

    Best-effort and fail-open: an empty mapping never blocks execution - the
    sandbox's injected ``curio_load_data`` / ``curio_data_path`` raise a clear
    per-id error for anything missing. Only ids appearing as literal calls are
    found; a dynamically built id simply won't be in the mapping. *formats*, when
    given, is filled with how ``curio_load_data`` reads each resolved id.
    """
    ids = dataset_ids_in_code(code, limit=MAX_EXEC_DATASET_IDS)
    if not ids:
        return {}
    try:
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        service = DatasetCatalogService(user)
        if formats is None:
            return service.resolve_execution_paths(ids, dataflow_id=dataflow_id)
        return service.resolve_execution_paths(ids, dataflow_id=dataflow_id, formats=formats)
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[processPythonCode] dataset path resolution failed: {e}", flush=True)
        return {}


def resolve_models_for(code: str, user_key: str | None) -> dict:
    """``{model id: folder}`` for the models *code* runs as
    ``curio_load_model("<id>")`` that the store of *user_key* holds: models
    behave like nodes, so a model package never added gives none
    (``packages.service.resolve_model_dirs``). Fail-open like dataset paths:
    the sandbox's ``curio_load_model`` names a model that is not there."""
    from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

    ids = model_ids_in_code(code)
    if not ids:
        return {}
    try:
        from utk_curio.backend.app.packages.service import resolve_model_dirs

        return resolve_model_dirs(user_key, ids)
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[processPythonCode] model resolution failed: {e}", flush=True)
        return {}


def resolve_models(code: str, user) -> dict:
    """:func:`resolve_models_for` the account *user* runs as."""
    return resolve_models_for(code, exec_user_key(user))


def resolve_package_modules(
    node_type: str, user_key: str | None, dataflow_id: str | None = None,
) -> dict | list | None:
    """The modules the node's package ships beside its templates, and those of
    the packages it depends on, which the sandbox makes importable for this
    run (#468): ``{"root", "names"}``, a list of them, or None for a node
    whose package ships none and depends on none. Fail-open like dataset
    paths."""
    from utk_curio.backend.app.packages.service import modules_for_node

    return modules_for_node(user_key, node_type, dataflow_id)


def resolve_secrets(code: str, user) -> dict:
    """Resolve the connection keys *code* reaches as ``curio_secret("<name>")``
    (memo dev/116) to their values: the ``dataset_paths`` twin, minus the disk.

    Best-effort and fail-open like ``resolve_dataset_paths``: an empty
    mapping never blocks execution; the sandbox's injected ``curio_secret``
    names the missing key. Values leave this function only inside the sandbox
    request body; they are never logged and never echoed to the browser.
    """
    from utk_curio.backend.app.users.connection_keys import secret_names

    names = secret_names(code)
    if not names:
        return {}
    try:
        from utk_curio.backend.app.users.connection_keys import default_store, storage_key_for

        user_key = storage_key_for(user)
        return default_store().resolve(user_key, names)
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[processPythonCode] connection-key resolution skipped: {e.__class__.__name__}", flush=True)
        return {}


def exec_user_key(user):
    """The user's on-disk storage key, or None when there is no user.

    Matches the key ``auto_install_node_output`` files a node's output under,
    so a user's work directory and their computed datasets agree about who they
    belong to. Returns None rather than raising: an unauthenticated launch
    (``CURIO_NO_AUTH=1``) has no user, and the sandbox then falls back to the
    launch directory exactly as it did before.
    """
    try:
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(user) if user is not None else None
    except Exception:  # noqa: BLE001 - a work directory is a convenience
        return None


def record_runtime_outcome(user, *, node_id, dataflow_id, code, stdout, stderr, output, duration_ms):
    """Per-node runtime journal write (memo dev/67-2, DEC-052).

    Best-effort and observational: agents read this to answer "what ran, what
    failed, and why"; an execution response is never delayed or failed over
    it. Skipped when the run has no node/project identity (unsaved canvas)."""
    from utk_curio.backend.app.execution import runtime_journal
    from utk_curio.backend.app.projects.services import _user_dir_key

    if not node_id or not dataflow_id or user is None:
        return
    try:
        runtime_journal.record_execution(
            _user_dir_key(user), dataflow_id, node_id,
            code=code, stdout=stdout, stderr=stderr, output=output,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            duration_ms=duration_ms,
        )
    except Exception:
        pass


def execute_python_node(user, session_token: str | None, run: NodeRun) -> tuple[dict, int]:
    """Run one Python node as *user*, its artifacts tagged with *session_token*.

    Returns the ``/processPythonCode`` reply body and its status. Raises
    :class:`~utk_curio.backend.app.execution.sandbox_client.SandboxTransportError`
    when the sandbox could not be asked.
    """
    return _execute(user, session_token, run, language="python")


def execute_js_node(user, session_token: str | None, run: NodeRun) -> tuple[dict, int]:
    """:func:`execute_python_node` for a JavaScript node (``/processJavaScriptCode``)."""
    return _execute(user, session_token, run, language="javascript")


@dataclass(frozen=True)
class _KeptRun:
    """The kept session an owner's run of a saved dataflow runs in, and
    whether what it reads is the owner's alone (``kept.OWNER_ONLY``)."""

    session_id: str
    private: bool


def _kept_run(user, run: NodeRun, input_ref: dict, saved_inputs: dict) -> _KeptRun | None:
    """A kept session for this run (``common/kept_sessions.py``) when it is
    the owner's run of a saved dataflow that reads only that dataflow's
    outputs: those the owner's runs kept, and those it saved. Its output is
    then kept too (``runs/kept.py``), and the owner reads it through the
    dataflow's routes, under any sign-in, for as long as it is kept.

    Anything else runs in the caller's own session, as before: a
    collaborator's play, an unsaved canvas, and a run whose input is not the
    dataflow's, such as one made before its first save. The sandbox lets a
    kept session read any kept output, so only this dataflow's names may
    reach one. A saved output is read from the store first, so a name its
    manifest records that a kept run made, and the owner's runs did not
    keep, is not one: the sandbox would read that run's artifact, whoever's
    it is.
    """
    if user is None or not run.dataflow_id or not run.node_id:
        return None
    from utk_curio.backend.app.datasets.infrastructure.sandbox_artifacts import made_by_a_kept_run
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.extensions import db
    from utk_curio.common.kept_sessions import new_session_id

    try:
        project = db.session.get(Project, run.dataflow_id)
    except Exception:  # noqa: BLE001 - a run never fails on this lookup
        return None
    if project is None or project.user_id != getattr(user, "id", None):
        return None
    names = input_names(input_ref)
    if len(names) > MAX_SAVED_INPUTS:
        return None
    private = False
    for name in names:
        entry = kept.owner_entry(run.dataflow_id, name)
        if entry is not None:
            private = private or entry.private_to is not None
        elif name not in saved_inputs or made_by_a_kept_run(name):
            return None
    return _KeptRun(session_id=new_session_id(), private=private)


def _forget_kept_run(kept_run: _KeptRun | None) -> None:
    """Forget what a kept run that failed made, if it made anything."""
    if kept_run is not None:
        from utk_curio.backend.app.runs import kept

        kept.forget_sessions([kept_run.session_id])


def _keep_owner_output(user, run: NodeRun, kept_run: _KeptRun, output, *,
                       language: str, used_keys: bool, dataset_paths: dict | None) -> None:
    """Keep the output of an owner's run (:func:`_kept_run`) under the key a
    viewer's run of the same step computes (``runs/viewer.py``), or forget
    its session when it made none. Private when the owner's keys made it, or
    anything it read."""
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.runs import kept

    if not (isinstance(output, dict) and output.get("path")):
        _forget_kept_run(kept_run)
        return
    try:
        key = kept.step_key(
            packages=kept.packages_fingerprint(_user_dir_key(user)),
            node_type=run.node_type, engine=language, code=run.code,
            input_ref=kept.input_identity(run.input), input_slots=run.input_slots,
            datasets=kept.datasets_read(run.code, run.dataflow_id, user, paths=dataset_paths),
        )
        kept.keep(
            run.dataflow_id, run.node_id, key, kept_run.session_id, output,
            private_to=kept.OWNER_ONLY if (kept_run.private or used_keys) else None,
            made_by=kept.MADE_BY_OWNER,
        )
    except Exception as e:  # noqa: BLE001 - the run's reply goes out either way
        print(f"[node_exec] could not keep the output of node {run.node_id}: "
              f"{e.__class__.__name__}: {e}", flush=True)


def _execute(user, session_token, run: NodeRun, *, language: str) -> tuple[dict, int]:
    t0 = time.perf_counter()
    label = _LABELS[language]
    tag = label.lstrip('/')
    input_ref = parse_input_ref(run.input)
    saved_inputs = resolve_saved_inputs(input_ref, run.dataflow_id)
    kept_run = _kept_run(user, run, input_ref, saved_inputs)

    body = {
        "code": run.code,
        "file_path": input_ref['path'],
        "nodeType": run.node_type,
        "dataType": input_ref['dataType'],
        "session_id": kept_run.session_id if kept_run else session_token,
        # The imports a node's code ran stay the caller's, so an upstream
        # node's `import numpy as np` reaches a downstream one (#158), kept
        # session or not.
        "imports_session": session_token,
        "save_dataset": run.save_output_dataset,
    }
    if run.input_slots:
        body["input_slots"] = list(run.input_slots)
    if saved_inputs:
        body["saved_paths"] = saved_inputs
    dataset_paths = None
    exec_secrets = None
    if language == "python":
        from utk_curio.backend.app.datasets.infrastructure import left_out_files

        endpoint = '/exec'
        dataset_formats: dict = {}
        # On a pip install, a dataset or model file its package leaves out is
        # downloaded as it resolves. A download that fails ends the run here,
        # with its own error, where the sandbox would only say "not available".
        with left_out_files.failures() as unavailable:
            dataset_paths = resolve_dataset_paths(run.code, run.dataflow_id, user, dataset_formats)
            exec_models = resolve_models(run.code, user)
        if unavailable:
            return _unavailable_reply(user, run, input_ref, unavailable, started=t0), 200
        # Under isolation the sandbox gives each user a persistent work directory,
        # so a node's relative reads and writes land somewhere that belongs to
        # them instead of the launch tree. The storage key, not a name, and only
        # the backend knows it: the sandbox has no notion of who is logged in, and
        # the in-process path ignores it entirely.
        user_key = exec_user_key(user)
        collections, media_dir = resolve_exec_collections(run.code, user_key, user=user)
        exec_secrets = resolve_secrets(run.code, user)
        package_modules = resolve_package_modules(run.node_type, user_key, run.dataflow_id)
        body.update({
            "dataset_paths": dataset_paths,
            "dataset_formats": dataset_formats,
            "user_key": user_key,
            "collections": collections,
            "media_dir": media_dir,
            # dev/116: present only when the code names a saved key; the
            # request body is otherwise byte-identical to before.
            **({"secrets": exec_secrets} if exec_secrets else {}),
            # Likewise only when the code runs a model.
            **({"models": exec_models} if exec_models else {}),
            # And only when the node's package ships modules beside its templates.
            **({"package_modules": package_modules} if package_modules else {}),
        })
    else:
        endpoint = '/execJs'
    t1 = time.perf_counter()
    # The gauge wraps only the sandbox round trip, which is where a node
    # actually spends its time. Counting the surrounding parse and JSON work
    # would report nodes as "running" that are really just being serialised.
    # The round trip includes a wait for the node's place in the sandbox, which
    # the timeout does not count: the sandbox keeps the connection busy until
    # the node runs (#889).
    with _monitor_counters.in_flight():
        response = sandbox_request(
            'post', endpoint,
            label=label, timeout=SANDBOX_EXEC_TIMEOUT,
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
    t2 = time.perf_counter()

    try:
        response_json = response.json()
    except Exception as e:
        print(f"[{tag}] sandbox {endpoint} returned non-JSON: "
              f"status={response.status_code} "
              f"body={response.text[:500]!r}", flush=True)
        _forget_kept_run(kept_run)
        return {
            'stdout': '',
            'stderr': f'Sandbox error: {e}',
            'input': input_ref,
            'output': {}
        }, 500
    if response_json.get('error'):
        # The sandbox failed the run itself, after its status had gone out (#889).
        print(f"[{tag}] sandbox {endpoint} failed: "
              f"{response_json['error']}: {response_json.get('message')}", flush=True)
        _forget_kept_run(kept_run)
        return {
            'stdout': '',
            'stderr': f"Sandbox error: {response_json['error']}: {response_json.get('message')}",
            'input': input_ref,
            'output': {}
        }, 500

    stdout = response_json['stdout']
    stderr = response_json['stderr']
    output = response_json['output']
    if kept_run is not None:
        _keep_owner_output(
            user, run, kept_run, output, language=language,
            used_keys=bool(exec_secrets), dataset_paths=dataset_paths,
        )

    t3 = time.perf_counter()
    print(
        f"[backend {label}] parse={t1-t0:.3f}s"
        f"  sandbox_rtt={t2-t1:.3f}s"
        f"  json={t3-t2:.3f}s"
        f"  total={t3-t0:.3f}s"
        f"  node={run.node_type}",
        flush=True,
    )

    # Auto-install into the user store (not the public Data Catalog).
    from utk_curio.backend.app.datasets.application.auto_install import auto_install_node_output

    installed_dataset = None
    dataset_diagnostic = None
    if run.save_output_dataset and isinstance(output, dict) and run.node_id:
        dataset_diagnostic = auto_install_node_output(
            user=user,
            node_id=run.node_id,
            sandbox_output=output,
            dataflow_id=run.dataflow_id,
            node_name=run.node_name,
            node_type=run.node_type,
        )
        if dataset_diagnostic.get("status") == "installed":
            installed_dataset = dataset_diagnostic.get("dataset")
            print(
                f"[{tag}] auto-installed dataset "
                f"{installed_dataset.get('id')} for node {run.node_id}",
                flush=True,
            )
        else:
            print(
                f"[{tag}] node {run.node_id} produced no computed dataset: "
                f"{dataset_diagnostic.get('status')} - {dataset_diagnostic.get('reason')}",
                flush=True,
            )

    record_runtime_outcome(
        user,
        node_id=run.node_id,
        dataflow_id=run.dataflow_id,
        code=run.code, stdout=stdout, stderr=stderr, output=output,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )

    # Deliberately a SIBLING of the journal call, not a line inside it:
    # record_runtime_outcome returns early whenever node/dataflow/user is
    # missing, which is every execution from an unsaved canvas. Counters placed
    # in there would silently under-count exactly the runs a new user makes.
    _monitor_counters.record_execution(
        language=language,
        node_type=run.node_type,
        ok=bool(isinstance(output, dict) and output.get("path")),
        duration_ms=(time.perf_counter() - t0) * 1000.0,
    )
    if not (isinstance(output, dict) and output.get("path")):
        # Same canonical predicate as above: an EMPTY output path. A non-empty
        # stderr is NOT the predicate, because benign warnings land there too
        # and logging those as errors would bury the real ones.
        _monitor_errors.record(
            "node",
            summary=_monitor_errors.summarise_traceback(stderr) or "Node execution failed",
            detail=str(stderr or ""),
            context={"nodeType": run.node_type, "language": language},
        )

    reply = {
        'stdout': stdout,
        'stderr': stderr,
        'input': input_ref,
        'output': output,
        'installedDataset': installed_dataset,
        'datasetDiagnostic': dataset_diagnostic,
    }
    if language == "python":
        reply['missingModule'] = _missing_module(user, output, stderr)
    return reply, 200


def _unavailable_reply(user, run: NodeRun, input_ref: dict, unavailable: dict, *, started: float) -> dict:
    """The reply of a Python run whose code reads a file the pip package
    leaves out that could not be downloaded (*unavailable*, ``{repo path:
    message}``): a failed run whose error is the download's own, recorded as
    a failed run is. The sandbox is not asked to run code that would fail at
    that read."""
    stderr = "\n\n".join(unavailable.values())
    output = {'path': '', 'dataType': 'str'}
    duration_ms = (time.perf_counter() - started) * 1000.0
    record_runtime_outcome(
        user, node_id=run.node_id, dataflow_id=run.dataflow_id, code=run.code,
        stdout=[], stderr=stderr, output=output, duration_ms=duration_ms,
    )
    _monitor_counters.record_execution(
        language="python", node_type=run.node_type, ok=False, duration_ms=duration_ms,
    )
    _monitor_errors.record(
        "node",
        summary="A file the pip package leaves out could not be downloaded",
        detail=stderr,
        context={"nodeType": run.node_type, "language": "python"},
    )
    return {
        'stdout': [],
        'stderr': stderr,
        'input': input_ref,
        'output': output,
        'installedDataset': None,
        'datasetDiagnostic': None,
        'missingModule': None,
    }


def _missing_module(user, output, stderr):
    """Which library the run was missing, when that is why it failed (#299).

    Gated on the canonical failure contract - an EMPTY output path, not a
    non-empty stderr, because warnings land in stderr too. `detect` never
    raises: a diagnostic that turned one failure into two would be worse than
    none, and the traceback is reported either way.
    """
    if not (isinstance(output, dict) and not output.get('path')):
        return None
    from utk_curio.backend.app.packages.application import missing_import
    from utk_curio.backend.app.users.capabilities import library_install_refusal

    missing_module = missing_import.detect(stderr)
    # Never offer an install the libraries route would refuse (#309).
    refusal = library_install_refusal(user)
    if missing_module and missing_module.get("installable") and refusal:
        missing_module = {
            **missing_module,
            "installable": False,
            "reason": "install-disabled",
            "detail": refusal,
        }
    return missing_module
