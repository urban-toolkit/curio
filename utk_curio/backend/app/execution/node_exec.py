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
    # The wired circles, in order: which input_k each value of *input* is.
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


#: What a run that cannot save is told when its code saves a file.
UNSAVED_DATAFLOW_REASON = (
    "Save the dataflow first: curio_save_file and curio_save_folder keep files "
    "in the dataflow's Computed datasets, and this dataflow has not been saved yet."
)


def resolve_computed(code: str, dataflow_id: str | None, user, dataset_paths: dict, formats: dict | None = None) -> dict:
    """What the sandbox's saved-file helpers need for one run (``sandbox/util/saved_files.py``).

    Each ``curio_computed_path("<name>")`` the code reads is the dataset
    ``computed.<dataflowId>.files.<name>``; the ones that resolve are added to
    *dataset_paths* (and *formats*), so they are staged like any dataset, and
    named in ``names``. ``canSave`` says whether the run may save at all: a
    saved file belongs to a dataflow, so one with no id cannot. Fail-open like
    dataset paths: a name that does not resolve is the helper's own error.
    """
    from utk_curio.backend.app.datasets.domain.saved_files import computed_names_in_code

    can_save = bool(dataflow_id) and user is not None
    computed = {"names": {}, "canSave": can_save, "reason": "" if can_save else UNSAVED_DATAFLOW_REASON}
    names = computed_names_in_code(code)
    if not names or not dataflow_id or user is None:
        return computed
    try:
        from utk_curio.backend.app.datasets.install.saved import saved_dataset_id
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        ids = {name: saved_dataset_id(dataflow_id, name) for name in names}
        service = DatasetCatalogService(user)
        if formats is None:
            paths = service.resolve_execution_paths(list(ids.values()), dataflow_id=dataflow_id)
        else:
            paths = service.resolve_execution_paths(list(ids.values()), dataflow_id=dataflow_id, formats=formats)
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[processPythonCode] saved-file resolution failed: {e}", flush=True)
        return computed
    for name, dataset_id in ids.items():
        if dataset_id in paths:
            dataset_paths[dataset_id] = paths[dataset_id]
            computed["names"][name] = dataset_id
    return computed


def install_saved_files(user, run: "NodeRun", output) -> list | None:
    """Install what the run saved (``output["savedFiles"]``) as computed
    datasets of its dataflow; None when it saved nothing."""
    saved = output.get("savedFiles") if isinstance(output, dict) else None
    if not saved or user is None or not run.dataflow_id:
        return None
    from utk_curio.backend.app.datasets.install.saved import install_saved_files as _install
    from utk_curio.backend.app.projects.services import _user_dir_key

    user_key = _user_dir_key(user)
    dataflow_name = None
    try:
        from utk_curio.backend.app.projects import storage as project_storage

        spec = project_storage.read_spec(user_key, run.dataflow_id)
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        if isinstance(dataflow, dict):
            dataflow_name = dataflow.get("name") or None
    except Exception:  # noqa: BLE001 - the name is lineage, best-effort
        pass
    return _install(
        user_key, saved,
        dataflow_id=run.dataflow_id, node_id=run.node_id,
        node_type=run.node_type, dataflow_name=dataflow_name,
    )


def resolve_models(code: str, user) -> dict:
    """The Model Catalog folders of the models *code* runs as
    ``curio_load_model("<id>")``, for this account. Fail-open like dataset paths:
    the sandbox's ``curio_load_model`` names a model that is not there."""
    from utk_curio.backend.app.model_catalog.service import resolve_exec_models

    return resolve_exec_models(code, user)


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
    if run.input_slots:
        body["input_slots"] = list(run.input_slots)
    if language == "python":
        from utk_curio.backend.app.datasets.infrastructure import left_out_files

        endpoint = '/exec'
        dataset_formats: dict = {}
        # On a pip install, a dataset or model file its package leaves out is
        # downloaded as it resolves. A download that fails ends the run here,
        # with its own error, where the sandbox would only say "not available".
        with left_out_files.failures() as unavailable:
            dataset_paths = resolve_dataset_paths(run.code, run.dataflow_id, user, dataset_formats)
            computed = resolve_computed(run.code, run.dataflow_id, user, dataset_paths, dataset_formats)
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
            "computed": computed,
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

    # What the code saved with curio_save_file / curio_save_folder, whatever
    # the save-output toggle says: the node asked for it by name.
    saved_datasets = install_saved_files(user, run, output)

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
    if saved_datasets:
        reply['savedDatasets'] = saved_datasets
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
