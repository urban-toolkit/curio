"""What a pip install of Curio reads, asked of the installed copy itself.

``test_pip_wheel_layout.py`` unpacks the wheel into an empty site-packages and
runs this source with ``python -c``, with nothing but that site-packages on
PYTHONPATH, an empty folder to start from and a HOME of its own. It prints,
after ``MARKER``, a JSON report: where each reader of the folders Curio ships
beside its code looks, and what it finds there.

It calls only what Curio had before its wheel kept those folders inside
``utk_curio/``, and it opens no socket: pip is replaced, ``curio test`` runs
nothing, and the launcher's DuckDB seeding copies files.
"""

import contextlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

MARKER = "PIP-INSTALL-PROBE "


def _names(paths):
    return sorted(Path(path).name for path in paths)


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

    from utk_curio.backend.app.packages.application.catalog import catalog_listing
    from utk_curio.backend.app.packages.repositories import catalog_dir

    report["packages"] = {
        "root": str(catalog_dir.catalog_root()),
        "listed": sorted(package["dirName"] for package in catalog_listing("guest")["packages"]),
    }

    print(MARKER + json.dumps(report))


if __name__ == "__main__":
    main()
