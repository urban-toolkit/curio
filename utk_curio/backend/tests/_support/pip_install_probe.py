"""What a pip install of Curio reads, asked of the installed copy itself.

``test_pip_wheel_layout.py`` unpacks the wheel into an empty site-packages and
runs this source with ``python -c``, with nothing but that site-packages on
PYTHONPATH, an empty folder to start from and a HOME of its own. Its one
argument is a JSON list of the repository paths to ask ``/file/`` for. It
prints, after ``MARKER``, a JSON report: where each reader of the folders Curio
ships beside its code looks, and what it finds there.

It calls only what Curio had before its wheel kept those folders, and the
parts of ``docs/`` it reads, inside ``utk_curio/``, and it opens no socket:
pip is replaced, ``curio test`` runs nothing, the launcher's DuckDB seeding
copies files, and ``/file/`` answers a test client. A reader of ``docs/`` that
raises is reported with its error, so the others still run.
"""

import builtins
import contextlib
import functools
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

MARKER = "PIP-INSTALL-PROBE "

#: A path in ``docs/examples/data/`` as a node of a shipped dataflow spells it:
#: in a Python node's code, or in an Autark node's ``pbfFileUrl``.
EXAMPLE_DATA_PATH = re.compile(r"docs/examples/data/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


def example_data_paths(text):
    """The paths in ``docs/examples/data/`` that *text* spells."""
    return {match.group(0).rstrip(".") for match in EXAMPLE_DATA_PATH.finditer(text or "")}


def python_nodes_reading_example_data():
    """Each Python node of a shipped dataflow that spells a path in
    ``docs/examples/data/``: its dataflow's key and its id, its type, and its
    code as a run resolves it."""
    from utk_curio.backend.app.execution import workflow_spec
    from utk_curio.backend.app.projects.shipped import shipped_dataflows

    python_types = set(workflow_spec.package_code_types())
    nodes = []
    for dataflow in shipped_dataflows():
        spec = workflow_spec.parse_workflow(str(dataflow.path))
        for node in spec.nodes:
            python = node.type in workflow_spec.PY_CODE_TYPES or node.raw_type in python_types
            if python and example_data_paths(node.content):
                nodes.append({
                    "key": f"{dataflow.key}/{node.id}",
                    "type": node.raw_type,
                    "code": spec.node_code(node, "python"),
                })
    return nodes


def _names(paths):
    return sorted(Path(path).name for path in paths)


def _guarded(read):
    """What *read*() returns, or ``{"error": ...}`` with the error it raised."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - the report names the error
        return {"error": f"{type(exc).__name__}: {exc}"}


def _shipped_dataflows():
    """The dataflows Curio seeds and lists (``projects/shipped.py``), and the
    packages and datasets ``--with-examples`` provisions for them."""
    from utk_curio.backend.app.datasets.seed import example_dep_dataset_dirs
    from utk_curio.backend.app.packages.service import example_dep_package_ids
    from utk_curio.backend.app.projects import shipped

    return {
        "root": str(shipped.examples_dir()),
        "keys": [dataflow.key for dataflow in shipped.shipped_dataflows()],
        "packages": list(example_dep_package_ids()),
        "datasets": list(example_dep_dataset_dirs()),
    }


def _worked_examples():
    """The shipped dataflows an agent's run may be shown (``turns/examples.py``)."""
    from utk_curio.backend.app.agents.application.turns import examples

    return [example.key for example in examples.used_examples()]


def _prompt_fixtures():
    """The agent evaluation's prompt fixtures (``evaluation/fixtures.py``),
    each validated against its schema; those whose example is the one they
    were written for; the examples it covers; and what an empty fixture
    raises."""
    from utk_curio.backend.app.agents.evaluation import fixtures

    loaded = fixtures.load_fixtures()
    empty = _guarded(lambda: fixtures.validate_fixture_dict({}, where="an empty fixture"))
    return {
        "root": str(fixtures.FIXTURE_ROOT),
        "schema": str(fixtures.FIXTURE_SCHEMA_PATH),
        "fixtures": [fixture.fixture_id for fixture in loaded],
        "digests_match": [fixture.fixture_id for fixture in loaded if fixtures.digest_matches(fixture)],
        "examples": [path.relative_to(fixtures.EXAMPLES_ROOT).as_posix() for path in fixtures.example_paths()],
        "an_empty_fixture": empty["error"].split(":")[0] if isinstance(empty, dict) else "accepted",
    }


def _folder_root(path):
    """Where the shipped Discovery source at *path* keeps its files, when it
    is a folder source; None for any other."""
    from dataclasses import replace

    from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest_from_dir
    from utk_curio.backend.app.discovery.infrastructure import storage

    manifest = load_source_manifest_from_dir(path)
    if manifest.provider.type != "folder":
        return None
    return str(storage.storage_root(replace(manifest, origin=storage.origin_of(path))))


def _folder_sources():
    """Where each folder source of the Discovery Catalog keeps its files
    (``discovery/infrastructure/storage.py``), or the error that says why not,
    by source."""
    from utk_curio.backend.app.discovery.infrastructure import storage

    roots = {path.name: _guarded(functools.partial(_folder_root, path)) for path in storage.list_discovery_sources()}
    return {name: root for name, root in roots.items() if root is not None}


def _curio_test_script():
    """The scripts/test.sh that ``curio test`` looks for. It names a missing
    one, and would run one that is there: the run is recorded, not made."""
    from utk_curio.cli import test_runner

    ran = []
    call, which = subprocess.call, shutil.which
    subprocess.call = lambda cmd, **kwargs: ran.append(list(cmd)) or 0
    shutil.which = lambda name: f"/usr/bin/{name}"
    said = io.StringIO()
    try:
        with contextlib.redirect_stderr(said), contextlib.redirect_stdout(io.StringIO()):
            try:
                test_runner.run_tests([])
            except SystemExit:
                pass
    finally:
        subprocess.call, shutil.which = call, which
    if ran:
        return ran[0][1]
    missing = re.search(r"\[ERROR\] (.+?) not found\.", said.getvalue())
    return missing.group(1) if missing else said.getvalue()


def _launcher_dependencies():
    """What ``curio start`` would pip-install for the shipped packages: the
    merged ``dependencies.python`` its catalog walk hands to pip."""
    from utk_curio.backend.app.packages import service as packages_service
    from utk_curio.cli import dependencies

    asked = []
    packages_service.install_python_deps = lambda merged, **kwargs: asked.append(dict(merged))
    dependencies._report_unimportable_deps = lambda merged, *, block: None
    with contextlib.redirect_stdout(io.StringIO()):
        dependencies.install_manifest_dependencies()
    return asked


def _seeded_duckdb_extensions():
    """What the launcher seeds into ``~/.duckdb``, by path there."""
    from utk_curio.cli import dependencies

    with contextlib.redirect_stdout(io.StringIO()):
        dependencies.seed_duckdb_extensions()
    target = Path.home() / ".duckdb" / "extensions" / "extensions.duckdb.org"
    return sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())


def _file_route(paths):
    """What ``GET /file/<path>`` answers for each repository path in *paths*:
    the sha256 of the file it serves, or the status it gives instead."""
    from flask import Flask

    from utk_curio.backend.app.api import bp

    app = Flask("pip-install-probe", instance_path=str(Path.cwd() / "instance"))
    app.register_blueprint(bp, url_prefix="")
    client = app.test_client()
    answers = {}
    for path in paths:
        response = client.get(f"/file/{quote(path)}", buffered=True)
        answers[path] = hashlib.sha256(response.data).hexdigest() if response.status_code == 200 else response.status_code
    return answers


def _in_process_runs(nodes):
    """What each node of *nodes* reports when the sandbox runs it in-process
    (``worker.execute_code``, a launch's default) in the folder Curio started
    from."""
    from utk_curio.sandbox.app import worker
    from utk_curio.sandbox.util.db import init_db

    init_db()
    worker._worker_init()
    runs = {}
    for node in nodes:
        result = worker.execute_code(
            textwrap.indent(node["code"], "    "), "", node["type"], "",
            launch_dir=os.environ["CURIO_LAUNCH_CWD"], session_id="pip-install-probe", save_dataset=False,
        )
        runs[node["key"]] = {"stderr": result["stderr"], "dataType": result["output"]["dataType"]}
    return runs


def _isolated_runs(nodes):
    """What each node of *nodes* reports in an isolated run's work directory,
    prepared as ``isolation/runner.py`` prepares a user's, entered as
    ``child.confine`` enters it, and run by ``child.run_node``, the code a
    forked child runs (the fork and the confinement need Linux); and where the
    ``docs/`` that directory holds leads."""
    from utk_curio.sandbox.isolation import child, supervisor
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    shared = str(_shared_data_dir())
    work = supervisor.prepare_user_work_dir(supervisor.user_work_dir(shared, "pip-install-probe"))
    started_in = os.getcwd()
    runs = {}
    for node in nodes:
        request = {
            "code": textwrap.indent(node["code"], "    "),
            "node_type": node["type"],
            "data_type": "",
            "scratch_dir": supervisor.make_scratch_dir(shared),
            "input": {"kind": "none"},
            "dataset_paths": {},
            "session_imports": [],
            "limits": {},
        }
        os.chdir(work)
        try:
            manifest = child.run_node(request, lambda: {"__builtins__": builtins})
        finally:
            os.chdir(started_in)
        runs[node["key"]] = {"ok": manifest["ok"], "stderr": manifest["stderr"]}
    return {"docs": os.path.realpath(os.path.join(work, "docs")), "runs": runs}


def _agent_eval_out():
    """Where ``agent_eval run`` writes its reports when no ``--out`` is given."""
    from utk_curio.tools import agent_eval

    return str(agent_eval.build_parser().parse_args(["run"]).out)


def main():
    import utk_curio

    report = {"utk_curio": str(Path(utk_curio.__file__).resolve().parent)}

    import datasets

    report["import_datasets"] = str(Path(datasets.__file__).resolve()) if getattr(datasets, "__file__", None) else None

    from utk_curio.backend.app.datasets.infrastructure import storage as dataset_storage
    from utk_curio.backend.app.datasets.repositories.registry import DatasetRegistryRepository

    report["datasets"] = {
        "root": str(dataset_storage.catalog_root()),
        "items": [
            {"dirName": item["dirName"], "path": item["path"], "sizeBytes": item["sizeBytes"]}
            for item in DatasetRegistryRepository().list_items()
        ],
    }

    from utk_curio.backend.app.model_catalog.infrastructure import storage as model_storage

    report["models"] = {"root": str(model_storage.models_root()), "listed": _names(model_storage.list_shipped_models())}

    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage

    report["discovery"] = {
        "root": str(discovery_storage.discovery_root()),
        "listed": _names(discovery_storage.list_discovery_sources()),
    }

    from utk_curio.sandbox.util import node_runtime

    report["duckdb_extensions"] = {"root": str(node_runtime.duckdb_extensions_dir()), "seeded": _seeded_duckdb_extensions()}

    report["scripts"] = {"test_sh": _curio_test_script()}

    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    record = left_out_files.read_record()
    report["record"] = {
        "path": str(left_out_files.RECORD_PATH),
        "commit": record.commit if record else None,
        "sizes": {path: entry.size for path, entry in record.files.items()} if record else None,
    }

    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.execution import workflow_spec

    report["launcher_dependencies"] = _launcher_dependencies()
    report["package_code_types"] = workflow_spec.package_code_types()
    report["builtin_manifest"] = contracts._Sources().manifest

    report["dataflows"] = _guarded(_shipped_dataflows)
    report["worked_examples"] = _guarded(_worked_examples)
    report["trill_schema"] = _guarded(lambda: contracts._Sources().trill)
    report["default_preamble"] = _guarded(contracts.render_default_preamble)
    report["prompt_fixtures"] = _guarded(_prompt_fixtures)
    report["folder_sources"] = _guarded(_folder_sources)

    from utk_curio.backend.app.packages.application.catalog import catalog_listing
    from utk_curio.backend.app.packages.repositories import catalog_dir

    report["packages"] = {
        "root": str(catalog_dir.catalog_root()),
        "listed": sorted(package["dirName"] for package in catalog_listing("guest")["packages"]),
    }

    report["file_route"] = _guarded(functools.partial(_file_route, json.loads(sys.argv[1])))
    report["agent_eval_out"] = _guarded(_agent_eval_out)
    nodes = _guarded(python_nodes_reading_example_data)
    if isinstance(nodes, dict):
        report["in_process_runs"] = report["isolated_runs"] = nodes
    else:
        report["in_process_runs"] = _guarded(functools.partial(_in_process_runs, nodes))
        report["isolated_runs"] = _guarded(functools.partial(_isolated_runs, nodes))

    print(MARKER + json.dumps(report))


if __name__ == "__main__":
    main()
