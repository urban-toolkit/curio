"""Dependencies installed at launch: pip, package manifests, the sandbox's
Node.js packages, and DuckDB's extensions."""

import os
import shutil
import subprocess
import sys
import threading

from pathlib import Path

from utk_curio.cli.frontend_build import (
    NODE_MAJOR,
    _node_tree_is_stale,
    _read_node_version,
    _write_node_stamp,
)
from utk_curio.cli.lifecycle import shell_required
from utk_curio.cli.logs import (
    COLOR_BACKEND,
    COLOR_SANDBOX,
    log_always,
    log_error,
    log_info,
    log_warning,
)


def seed_duckdb_extensions():
    """Put Curio's copy of DuckDB's spatial extension where duckdb-wasm looks.

    autk-db's ``init()`` runs ``INSTALL spatial; LOAD spatial;``. In Node,
    duckdb-wasm keeps installed extensions under
    ``~/.duckdb/extensions/<repository>/<version>/<platform>/`` and only
    downloads one that is not there — so seeding that directory from
    ``vendor/duckdb-extensions/`` means a node never reaches
    extensions.duckdb.org: no 23 MB download on a cold container, nothing to
    flake (#318), and an offline install still runs Autark nodes.

    Copies only what is missing, and never fails a launch: without it the
    extension is downloaded exactly as before.
    """
    import shutil
    from pathlib import Path

    from utk_curio.sandbox.util import node_runtime

    source_root = node_runtime.duckdb_extensions_dir()
    if not source_root.is_dir():
        return
    target_root = Path.home() / ".duckdb" / "extensions" / "extensions.duckdb.org"
    seeded = []
    try:
        for source in source_root.rglob("*.wasm"):
            target = target_root / source.relative_to(source_root)
            if target.is_file() and target.stat().st_size == source.stat().st_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            seeded.append(str(target.relative_to(target_root)))
    except OSError as exc:
        log_warning(f"[DuckDB] could not seed the spatial extension ({exc}); "
                    f"it will be downloaded on demand instead")
        return
    if seeded:
        log_always(f"[DuckDB] seeded extension(s) into {target_root}: {', '.join(seeded)}")


def _skip_dep_install() -> bool:
    """``CURIO_SKIP_DEP_INSTALL=1``: trust the environment as it is.

    The parallel e2e driver starts several backend+sandbox pairs from one
    checkout. Without this every launcher would run ``pip install`` into the
    same interpreter and ``npm install`` into the same ``node_modules`` at the
    same time. The driver does one warm-up (``curio.py setup`` and a root
    ``npm install``) before the first pair starts.
    """
    return os.environ.get("CURIO_SKIP_DEP_INSTALL", "").strip().lower() in ("1", "true", "yes", "on")


#: What fails without the sandbox's Node.js packages.
_WITHOUT_NODE_PACKAGES = "Autark data nodes and OpenStreetMap downloads will fail"


def _ensure_root_node_modules(project_root: str) -> None:
    """Install the sandbox's Node.js packages (``@urban-toolkit/autk-db``),
    which Autark data nodes and OpenStreetMap downloads run, with ``npm install
    --prefix`` the folder ``node_runtime.nodejs_dir`` names for *project_root*,
    the folder that holds ``utk_curio/``.

    npm runs only in a folder that holds Curio's package.json: pointed at
    site-packages, npm takes the nearest folder above with a package.json or a
    node_modules as its project (``<env>/lib`` in a conda environment) and
    empties its node_modules.
    """
    if shutil.which("npm") is None:
        log_warning(
            "[Sandbox] npm not found in PATH, so the sandbox's Node.js packages are not "
            f"installed and {_WITHOUT_NODE_PACKAGES}. Install Node.js {NODE_MAJOR}."
        )
        return

    folder = _sandbox_nodejs_folder(Path(project_root))
    if folder is None:
        return

    # An unreadable version leaves the tree alone rather than wiping it on a
    # guess. An out-of-date one never reaches here: _require_supported_node
    # stops the launch before any server starts.
    node_version_raw, node_major = _read_node_version()
    if node_version_raw and _node_tree_is_stale(str(folder), node_major):
        log_info(
            f"[Sandbox] {folder / 'node_modules'} was installed by a different Node.js "
            f"major; reinstalling for Node.js {node_major}...",
            COLOR_SANDBOX, 0,
        )
        shutil.rmtree(folder / "node_modules", ignore_errors=True)

    # Run npm install unconditionally (mirrors the frontend's check_install_build):
    # it's idempotent and fast when the lockfile is already satisfied, and it
    # self-heals when Curio's package.json bumps @urban-toolkit/autk-db. Gating
    # on the autk-db directory merely *existing* (the previous behavior) skipped
    # the update and left the sandbox on a stale version whose API differs,
    # silently breaking server-side data loading.
    log_info(
        f"[Sandbox] Ensuring the sandbox's Node.js packages (@urban-toolkit/autk-db) in {folder}...",
        COLOR_SANDBOX, 0,
    )
    try:
        subprocess.run(
            ["npm", "install", "--prefix", str(folder), "--no-audit", "--no-fund"],
            check=True, cwd=str(folder), shell=shell_required,
        )
    except subprocess.CalledProcessError as e:
        log_error(
            f"[Sandbox] 'npm install' failed in {folder} (exit code {e.returncode}). "
            f"{_WITHOUT_NODE_PACKAGES}."
        )
    except Exception as e:
        log_error(f"[Sandbox] Failed to run 'npm install' in {folder}: {e}")
    else:
        if node_major:
            _write_node_stamp(str(folder), node_major)


def _sandbox_nodejs_folder(root: Path) -> Path | None:
    """The folder npm installs the sandbox's Node.js packages in, or None after
    logging why there is none: *root* when it holds Curio's package.json, else
    ``nodejs/`` in Curio's state directory, not a link, with the package.json
    and package-lock.json the package ships written into it."""
    from utk_curio.sandbox.util import node_runtime

    folder = node_runtime.nodejs_dir(root)
    if folder == root:
        return root.resolve()
    shipped = root / node_runtime.SHIPPED_PACKAGE_FILES
    for name in node_runtime.PACKAGE_FILES:
        if not (shipped / name).is_file():
            log_error(
                f"[Sandbox] {shipped / name} is missing, so npm is not run and "
                f"{_WITHOUT_NODE_PACKAGES}. Install Curio from its release on PyPI, or start "
                f"it from a clone."
            )
            return None
    if not node_runtime.is_curio_package_json(shipped / "package.json"):
        log_error(
            f"[Sandbox] {shipped / 'package.json'} is not Curio's, so npm is not run and "
            f"{_WITHOUT_NODE_PACKAGES}."
        )
        return None
    links = [path for path in (folder, folder / "node_modules") if path.is_symlink()]
    if links:
        log_error(
            f"[Sandbox] {links[0]} is a link to {links[0].resolve()}, so npm is not run and "
            f"{_WITHOUT_NODE_PACKAGES}. Remove the link; the next start creates the folder."
        )
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name in node_runtime.PACKAGE_FILES:
            data = (shipped / name).read_bytes()
            target = folder / name
            if target.is_file() and not target.is_symlink() and target.read_bytes() == data:
                continue
            partial = folder / f".{name}.partial"
            partial.write_bytes(data)
            os.replace(partial, target)
    except OSError as exc:
        log_error(
            f"[Sandbox] Could not write Curio's package.json into {folder} ({exc}), so npm is "
            f"not run and {_WITHOUT_NODE_PACKAGES}."
        )
        return None
    return folder.resolve()


def _run_pip(cmd: list[str], failure_label: str) -> None:
    """Stream ``pip``'s stdout+stderr line-by-line, gating each line on
    verbosity >= 2 via ``log_info``. The ``[Setup]`` banners around this
    call print unconditionally; pip's own chatter ("Requirement already
    satisfied", "Collecting …", "Successfully installed …") stays silent
    at the default verbosity. On non-zero exit, surface ``failure_label``
    via ``log_error`` and abort startup.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout is not None:
        for line in process.stdout:
            log_info(f"[pip] {line.rstrip()}", COLOR_BACKEND, 2)
    rc = process.wait()
    if rc != 0:
        log_error(f"{failure_label} (exit {rc}). Re-run with --verbose 2 to see pip's output.")
        sys.exit(1)


def install_framework_requirements() -> None:
    """``pip install -r requirements.txt`` for Curio's framework deps —
    the libraries the backend + sandbox Flask apps need at module load.
    Data-ops libs (pandas, geopandas, …) live in each node
    package's manifest and get installed by
    ``install_manifest_dependencies`` below.

    Idempotent: pip exits in ~1 s when every line is already satisfied,
    so we run unconditionally at ``curio start``.
    """
    req = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
    if not req.is_file():
        return
    log_info(f"[Setup] Ensuring framework deps from {req.name}...", COLOR_BACKEND, 0)
    _run_pip(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        f"[Setup] pip install -r {req.name} failed",
    )


def _install_user_node_deps_at_boot(user_key: str, entries) -> None:
    """Provision one user's node libraries into their own tree (#332).

    Best-effort per user, unlike the host install below, which exits non-zero.
    One account's unsatisfiable manifest must not stop an instance booting for
    everybody else - the failure belongs to whoever installed that package, and
    they get a plain ImportError naming it the first time a node runs.
    """
    from utk_curio.backend.app.packages.infrastructure import backend_runtime
    from utk_curio.backend.app.packages.service import merge_python_deps
    from utk_curio.backend.app.packages.infrastructure.pip_runner import install_python_deps_to_target
    from utk_curio.backend.app.packages.service import PipInstallError

    merged, conflicts = merge_python_deps(entries)
    for c in conflicts:
        log_warning(
            f"Dependency range conflict for {c.package} (user {user_key}): "
            + ", ".join(f"{dn}={rng}" for dn, rng in c.ranges)
        )
    if not merged:
        return
    overlay = backend_runtime.user_node_overlay_dir(user_key)
    overlay.mkdir(parents=True, exist_ok=True)
    log_info(
        f"[Setup] Installing node deps for user {user_key}: "
        + ", ".join(sorted(merged)),
        COLOR_BACKEND, 0,
    )
    try:
        install_python_deps_to_target(
            merged, str(overlay),
            on_line=lambda line: log_info(f"[pip] {line}", COLOR_BACKEND, 2),
        )
    except PipInstallError as exc:
        log_error(f"[Setup] Node dep install failed for user {user_key}: {exc}")


def install_manifest_dependencies(*, block_on_verify: bool = False) -> None:
    """Walk every installed package manifest — catalog source-of-truth at
    ``<repo>/packages/`` PLUS every user store under
    ``$CURIO_LAUNCH_CWD/.curio/users/<u>/packages/`` — collect their
    ``dependencies.python`` maps, merge into a single conflict-aware
    union via ``resolver.merge_python_deps``, and pip-install the result
    through ``pip_runner.install_python_deps``.

    Why this lives in the launcher: the sandbox process imports
    ``pandas`` / ``geopandas`` at module load (``sandbox/app/api.py``
    triggers ``worker.py::_worker_init``), so those libs must already be
    present in the shared interpreter before the sandbox's ``Popen``
    lands. Running here — synchronously, sequenced before
    ``start_sandbox`` — is the simplest race-free order. (rasterio is
    optional: provided by raster-capable packages like curio.weather and
    imported lazily by the sandbox's raster code paths.)

    All helpers are reused from the backend:
    - ``manifest.load_package_manifest`` to parse each
      ``manifest.json`` into a typed dataclass with ``.python_deps``.
    - ``resolver.merge_python_deps`` to surface incompatible ranges as
      warnings instead of silently last-write-wins.
    - ``pip_runner.install_python_deps`` to do the pip work
      (PEP 440 + ``^X.Y`` caret rewrite + already-satisfied skip + batched
      pip + stderr-tail surfacing on failure).
    """
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import ManifestError
    from utk_curio.backend.app.packages.service import merge_python_deps
    from utk_curio.backend.app.packages.service import (
        PipInstallError,
        install_python_deps,
    )
    from utk_curio.backend.app.packages.service import example_dep_package_ids
    from utk_curio.backend.app.packages.infrastructure import backend_runtime
    from utk_curio.backend.app.packages.service import dep_destinations
    from utk_curio.backend.app.common.user_storage import users_base

    repo_root = Path(__file__).resolve().parent.parent.parent
    catalog = repo_root / "packages"
    # Asked of the backend rather than spelled out again: under CURIO_TESTING
    # the per-user tree is ``.curio/test/users/``, and this walk feeding off a
    # different root than the one the backend seeds into is a boot that
    # installs no dependencies at all while looking like it worked.
    users = users_base()

    per_pkg: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()  # dir_name dedupe across users

    # Catalog walk is scoped to ``curio.builtin@*`` by default — the
    # catalog lists every *available* package, but only the built-in is
    # auto-seeded for every user. Other catalog entries (UHVI,
    # weather, streetvision, …) are opt-in via the /catalog drawer;
    # their deps come along when the user installs them, via the
    # per-user-store walk below. When example seeding is on
    # (--with-examples => CURIO_SEED_EXAMPLES=1), also walk the
    # packages the bundled examples declare as dependencies — derived from
    # their dataflow.packages lockfiles (see example_dep_package_ids in
    # backend/app/packages/seed.py), NOT a full catalog walk. This
    # first-boot walk matters because it runs BEFORE the backend seeds those
    # packages into the user store; on later starts the user-store walk
    # below covers them.
    catalog_globs = ["curio.builtin@*"]
    if os.environ.get("CURIO_SEED_EXAMPLES") == "1":
        catalog_globs += [f"{pid}@*" for pid in example_dep_package_ids()]
    if catalog.is_dir():
        for pattern in catalog_globs:
            for pkg_dir in sorted(catalog.glob(pattern)):
                try:
                    m = load_package_manifest(pkg_dir)
                except ManifestError:
                    continue
                if m.dir_name in seen:
                    continue
                seen.add(m.dir_name)
                if m.python_deps:
                    per_pkg.append((m.dir_name, dict(m.python_deps)))

    # Per-user store walk — every package any user has actually installed.
    #
    # Routed, not unioned. ``dep_destinations`` is the one rule deciding where a
    # package's deps belong (backend_runtime, dev/97): "overlay" means a
    # backend-bearing package whose handlers read a private overlay and whose
    # promotion deliberately left the shared interpreter alone. Host-installing
    # those here at every boot silently undoes that boundary, and a version pin
    # in one user's manifest can then move a library every other user's nodes
    # depend on — merge_python_deps only warns, pip has the last word. Only
    # "host" and "both" name the shared interpreter as a destination.
    #
    # The glob is narrowed to the package-store layout for the same reason it is
    # walked at all: rglob would also match manifests nested inside a package's
    # own payload, which are not installed packages.
    #
    # #332: under fork isolation a node's libraries live in the calling
    # user's own tree, so this walk stops being one merged host install and
    # becomes one install per user. The dedupe below has to go with it: two
    # users who both installed curio.weather each need rasterio, in two
    # different directories, and ``seen`` would have given it to whichever of
    # them the glob reached first.
    per_user: dict[str, list[tuple[str, dict]]] = {}
    scoped = backend_runtime.per_user_node_envs()
    if users.is_dir():
        for mf in sorted(users.glob("*/packages/*/manifest.json")):
            try:
                m = load_package_manifest(mf.parent)
            except ManifestError:
                continue
            if not scoped and m.dir_name in seen:
                continue
            seen.add(m.dir_name)
            destination, why = dep_destinations(m)
            if destination not in ("host", "both"):
                log_info(
                    f"[Setup] Skipping {m.dir_name} deps: {why}",
                    COLOR_BACKEND, 2,
                )
                continue
            if not m.python_deps:
                continue
            if scoped:
                user_key = mf.parent.parent.parent.name
                per_user.setdefault(user_key, []).append(
                    (m.dir_name, dict(m.python_deps))
                )
            else:
                per_pkg.append((m.dir_name, dict(m.python_deps)))

    for user_key, entries in sorted(per_user.items()):
        _install_user_node_deps_at_boot(user_key, entries)

    if not per_pkg:
        return
    merged, conflicts = merge_python_deps(per_pkg)
    for c in conflicts:
        log_warning(
            f"Dependency range conflict for {c.package}: "
            + ", ".join(f"{dn}={rng}" for dn, rng in c.ranges)
        )
    if not merged:
        return
    log_info(
        f"[Setup] Installing manifest python deps for: {', '.join(sorted(merged))}",
        COLOR_BACKEND, 0,
    )
    try:
        install_python_deps(
            merged,
            on_line=lambda line: log_info(f"[pip] {line}", COLOR_BACKEND, 2),
        )
    except PipInstallError as exc:
        log_error(f"[Setup] Manifest dep install failed: {exc}")
        sys.exit(1)

    _report_unimportable_deps(merged, block=block_on_verify)


def _report_unimportable_deps(merged, *, block: bool) -> None:
    """Warn about deps that installed cleanly but cannot be imported.

    pip exiting 0 is not the same as the library working. A wheel whose native
    extension cannot load - the ordinary GDAL/CUDA case, and what a broken
    ``rasterio`` looks like on Windows - records a perfectly good version, so
    pip reports "already satisfied" and changes nothing on every subsequent
    start. This is the drifted env the caller above says it exists to catch, and
    without this check the first sign of it is a raw ``ImportError`` from
    whichever node happens to run first, long after a setup that looked clean.

    A warning, never a fatal: the stack is still useful and the nodes that avoid
    the library work normally. The fix is usually outside pip - a matching GDAL,
    a conda-forge build - so the decision is the operator's, and this line is
    what lets them make it.

    ``block=False`` runs the probe on a daemon thread, because it costs real
    time: importing the twelve builtin data-ops libraries in one subprocess
    takes ~19 s on a developer machine, which is too much to add to every
    ``start``. The warning then lands while the servers are coming up, which is
    early enough to be read. ``curio setup`` passes ``block=True``: it exits as
    soon as it returns, so a background thread would be killed before it
    reported, and waiting is the point of running setup explicitly.
    """
    def _probe() -> None:
        # Imported here, not at module scope: the launcher keeps backend
        # imports lazy, and resolving the attribute at call time
        # is also what lets a test stand in for the probe.
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        try:
            broken = pip_runner.import_failures(merged)
        except Exception as exc:  # noqa: BLE001 - never stop a boot over a probe
            log_warning(f"[Setup] Could not verify manifest deps import: {exc}")
            return
        for name, reason in sorted(broken.items()):
            log_warning(
                f"[Setup] {name} is installed but cannot be imported: {reason}. "
                f"Nodes that need it will fail when run."
            )

    if block:
        _probe()
    else:
        threading.Thread(target=_probe, name="dep-import-probe", daemon=True).start()
