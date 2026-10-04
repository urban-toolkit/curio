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
        )


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


def resolve_models(code: str, user) -> dict:
    """The Model Catalog folders of the models *code* runs as
    ``curio_load_model("<id>")``, for this account. Fail-open like dataset paths:
    the sandbox's ``curio_load_model`` names a model that is not there."""
    from utk_curio.backend.app.model_catalog.service import resolve_exec_models

    return resolve_exec_models(code, user)


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


def _execute(user, session_token, run: NodeRun, *, language: str) -> tuple[dict, int]:
    t0 = time.perf_counter()
    label = _LABELS[language]
    tag = label.lstrip('/')
    input_ref = parse_input_ref(run.input)

    body = {
        "code": run.code,
        "file_path": input_ref['path'],
        "nodeType": run.node_type,
        "dataType": input_ref['dataType'],
        "session_id": session_token,
        "save_dataset": run.save_output_dataset,
    }
    if language == "python":
        endpoint = '/exec'
        dataset_formats: dict = {}
        dataset_paths = resolve_dataset_paths(run.code, run.dataflow_id, user, dataset_formats)
        # Under isolation the sandbox gives each user a persistent work directory,
        # so a node's relative reads and writes land somewhere that belongs to
        # them instead of the launch tree. The storage key, not a name, and only
        # the backend knows it: the sandbox has no notion of who is logged in, and
        # the in-process path ignores it entirely.
        user_key = exec_user_key(user)
        collections, media_dir = resolve_exec_collections(run.code, user_key, user=user)
        exec_secrets = resolve_secrets(run.code, user)
        exec_models = resolve_models(run.code, user)
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
        })
    else:
        endpoint = '/execJs'
    t1 = time.perf_counter()
    # The gauge wraps only the sandbox round trip, which is where a node
    # actually spends its time. Counting the surrounding parse and JSON work
    # would report nodes as "running" that are really just being serialised.
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
        return {
            'stdout': '',
            'stderr': f'Sandbox error: {e}',
            'input': input_ref,
            'output': {}
        }, 500

    stdout = response_json['stdout']
    stderr = response_json['stderr']
    output = response_json['output']

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
