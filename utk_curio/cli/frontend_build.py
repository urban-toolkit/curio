"""Node.js version checks, node_modules stamps, and the frontend build."""

import json
import os
import re
import shutil
import subprocess
import sys

from utk_curio.cli.lifecycle import clean_shutdown, shell_required
from utk_curio.cli.logs import COLOR_FRONTEND, log_error, log_info, log_warning


# The Node.js major the project targets: the frontend build, Jest, and the
# sandbox's Node subprocess. Keep in step with the Dockerfile, .nvmrc,
# .node-version and both package.json "engines" fields --
# test_launcher_node_version.py fails when they drift.
NODE_MAJOR = 26

# Recorded inside node_modules by the Node major that installed it; a tree from
# another major (or with no stamp, i.e. any checkout from before Node 26) is
# reinstalled once. ``npm install`` alone does not heal it: it never re-runs an
# install script, and webpack's cache under node_modules/.cache is not keyed on
# the Node version.
NODE_STAMP = ".curio-node-major"


def _read_node_version():
    """``(raw, major)`` for the ``node`` on PATH; ``(None, 0)`` when unreadable."""
    try:
        raw = subprocess.check_output(
            ["node", "--version"], text=True, shell=shell_required,
        ).strip()
    except Exception as e:
        log_error(f"Could not determine Node.js version: {e}")
        return None, 0
    major = 0
    if raw.startswith("v"):
        try:
            major = int(raw[1:].split(".", 1)[0])
        except ValueError:
            pass
    return raw, major


def _node_tree_is_stale(root, major):
    """True when ``root``'s node_modules was installed by a different Node major.

    See ``NODE_STAMP``. A missing tree is not stale -- there is nothing to wipe
    and the install that follows is a fresh one.
    """
    node_modules = os.path.join(root, "node_modules")
    if not os.path.isdir(node_modules):
        return False
    try:
        with open(os.path.join(node_modules, NODE_STAMP), encoding="utf-8") as fh:
            return fh.read().strip() != str(major)
    except OSError:
        return True


def _require_supported_node():
    """Refuse to start on a Node older than the project targets.

    Serving a prebuilt bundle would survive it, but the sandbox runs autk-db in
    this Node, where Autark data nodes die mid-download (the undici regression
    nodejs/undici#5360), and every npm script fails against it. That is a broken
    install rather than a degraded one, and the failures it produces read as
    bugs in Curio. No Node at all is a different case: nothing to be wrong, and
    a Python-only session still works.

    Exits non-zero rather than through clean_shutdown, whose 0 would tell a
    script that the stack came up. Nothing is running yet to shut down.
    """
    if shutil.which("node") is None:
        return
    raw, major = _read_node_version()
    if raw is None or major >= NODE_MAJOR:
        return
    log_error(
        f"Node.js {raw} detected; Curio requires Node.js {NODE_MAJOR} or newer. "
        f"Upgrade with 'conda install -c conda-forge nodejs={NODE_MAJOR}' or "
        f"from https://nodejs.org, then retry."
    )
    sys.exit(1)


def _frontend_tree_is_stale():
    """node_modules belongs to another Node major, and Node is here to tell.

    Nothing to check without a tree (the container and pip ship none) or
    without Node on PATH. A *missing* tree is not stale: it fails obviously,
    one npm install away, and conjuring 1.6 GB nobody asked for would undo a
    deliberate delete.
    """
    if shutil.which("npm") is None or shutil.which("node") is None:
        return False
    if not os.path.isfile(os.path.join(_frontend_dir(), "package.json")):
        return False  # nothing to reinstall from, so nothing to report
    _, major = _read_node_version()
    return bool(major) and _node_tree_is_stale(_frontend_dir(), major)


def _write_node_stamp(root, major):
    """Record the Node major that installed ``root``'s node_modules.

    Called after a successful install only, so a failed one does not leave a
    stamp claiming the tree is current.
    """
    node_modules = os.path.join(root, "node_modules")
    try:
        os.makedirs(node_modules, exist_ok=True)
        with open(os.path.join(node_modules, NODE_STAMP), "w", encoding="utf-8") as fh:
            fh.write(str(major))
    except OSError as exc:
        # Unstamped counts as stale, so the only cost is one extra reinstall.
        log_warning(f"Could not record the installing Node.js major: {exc}")


def check_install_build(dir, force_rebuild=False):
    # Determine the absolute path whether it is provided as relative or absolute
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_dir = os.path.abspath(dir) if os.path.isabs(dir) else os.path.join(script_dir, dir)
    
    if not os.path.exists(abs_dir):
        raise FileNotFoundError(f"[Error] The directory '{abs_dir}' does not exist.")
    
    os.chdir(abs_dir)
    log_info(f"[Frontend] Current working directory for npm commands: {os.getcwd()}", COLOR_FRONTEND, 0)
    
    if shutil.which("npm") is None:
        log_error(f"[Frontend] npm not found in PATH. Install Node.js {NODE_MAJOR} from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs={NODE_MAJOR}'), and make sure 'npm' is available in your terminal, then retry.")
        clean_shutdown()
        return

    if shutil.which("node") is None:
        log_error(f"[Frontend] node not found in PATH. Install Node.js {NODE_MAJOR} from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs={NODE_MAJOR}'), and make sure 'node' is available in your terminal, then retry.")
        clean_shutdown()
        return
    node_version_raw, node_major = _read_node_version()
    if node_version_raw is None:
        clean_shutdown()
        return
    if node_major < NODE_MAJOR:
        log_error(
            f"[Frontend] Node.js {node_version_raw} detected; requires Node.js {NODE_MAJOR} or newer. "
            f"Upgrade with 'conda install -c conda-forge nodejs={NODE_MAJOR}' or from https://nodejs.org, then retry."
        )
        clean_shutdown()
        return

    # A tree from another Node major is reinstalled (see NODE_STAMP), and only
    # the tree: which Node ran webpack does not change the JavaScript it emits,
    # so the bundle is judged by its own stamp below and usually survives.
    if not force_rebuild and _node_tree_is_stale(abs_dir, node_major):
        log_info(
            f"[Frontend] node_modules was installed by a different Node.js major; "
            f"reinstalling for Node.js {node_major}...",
            COLOR_FRONTEND, 0,
        )
        shutil.rmtree(os.path.join(abs_dir, "node_modules"), ignore_errors=True)

    if force_rebuild:
        log_info(f"[Frontend] Force rebuilding in {dir}...", COLOR_FRONTEND)
        for subdir in ("node_modules", "dist", "build"):
            full_path = os.path.join(abs_dir, subdir)
            if os.path.exists(full_path):
                shutil.rmtree(full_path)

    # Run npm install unconditionally. It's idempotent and fast (~1 s) when
    # the lockfile is already satisfied, and it self-heals when package.json
    # gains a new dep that node_modules/ doesn't have yet — gating on
    # ``node_modules`` existing would skip the install and leave the new dep
    # missing, failing the webpack build with "Module not found".
    log_info(f"[Frontend] Ensuring npm deps are installed...", COLOR_FRONTEND, 0)
    try:
        subprocess.run(["npm", "install"], check=True, shell=shell_required)
    except subprocess.CalledProcessError as e:
        log_error(f"[Frontend] 'npm install' failed (exit code {e.returncode}). Check the output above for details.")
        clean_shutdown()
    except Exception as e:
        log_error(f"[Frontend] Failed to run 'npm install': {e}")
        clean_shutdown()
    else:
        _write_node_stamp(abs_dir, node_major)

    # The only output there is: webpack writes it and start_frontend serves it by
    # name. A ``"dist" if exists else "build"`` fallback used to stamp a build/
    # this function created itself, which then stood in for a deleted dist and
    # skipped the build (test_leftover_build_dir_does_not_suppress_the_build).
    # Same check start_frontend gates on, so the two never disagree about
    # whether the existing build is reusable.
    reason = _build_stamp_reason(abs_dir)

    if reason is not None:
        log_info(f"[Frontend] Running npm run build ({reason})...", COLOR_FRONTEND, 0)
        try:
            subprocess.run(["npm", "run", "build"], check=True, shell=shell_required)
        except subprocess.CalledProcessError as e:
            log_error(f"[Frontend] 'npm run build' failed (exit code {e.returncode}). Check the output above for details.")
            clean_shutdown()
        except Exception as e:
            log_error(f"[Frontend] Failed to run 'npm run build': {e}")
            clean_shutdown()
        else:
            # Written after a successful build only, so a failed one does not
            # leave a stamp claiming the bundle matches.
            _write_build_stamp(abs_dir)
    else:
        log_info("[Frontend] dist is current. Skipping npm run build.", COLOR_FRONTEND, 0)

def force_rebuild_frontend():
    log_info(f"[Frontend] Force rebuild requested.", COLOR_FRONTEND, 0)
    check_install_build("frontend/urban-workflows/", force_rebuild=True)
    log_info(f"[Frontend] Force rebuild complete.", COLOR_FRONTEND, 0)

def _frontend_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "urban-workflows"
    )


def _frontend_is_built(root: str = "") -> bool:
    return os.path.isfile(os.path.join(root or _frontend_dir(), "dist", "index.html"))


def _frontend_build_mode(root: str = "") -> str:
    """The webpack mode ``npm run build`` uses, read from package.json.

    Read rather than pinned so the stamp follows the script: flip the script
    between development and production and the next start rebuilds by itself.
    """
    try:
        pkg = os.path.join(root or _frontend_dir(), "package.json")
        with open(pkg, encoding="utf-8") as fh:
            script = json.load(fh).get("scripts", {}).get("build", "")
    except (OSError, ValueError):
        return "unknown"
    found = re.search(r"--mode\s+(\S+)", script)
    return found.group(1) if found else "unknown"


BUILD_STAMP = ".curio-build"


def _build_stamp_reason(root: str = "") -> str | None:
    """Why the built frontend cannot be reused, or None when it can.

    The build knows nothing of the instance it serves: the frontend server
    writes the backend address and the base path into the page. What the stamp
    records is the webpack mode. Every checkout built before the move to a
    production build carries a development bundle, three times the size, and
    nothing else would ever notice.
    """
    dist = os.path.join(root or _frontend_dir(), "dist")
    if not _frontend_is_built(root):
        return "dist directory not found"

    wanted_mode = _frontend_build_mode(root)
    built_mode = None
    try:
        with open(os.path.join(dist, BUILD_STAMP), encoding="utf-8") as fh:
            built_mode = fh.read().strip() or None
    except OSError:
        pass

    if built_mode != wanted_mode:
        return f"built in {built_mode or 'an unrecorded'} mode, need {wanted_mode}"
    return None


def _write_build_stamp(root: str = "") -> None:
    dist = os.path.join(root or _frontend_dir(), "dist")
    try:
        os.makedirs(dist, exist_ok=True)
        with open(os.path.join(dist, BUILD_STAMP), "w", encoding="utf-8") as fh:
            fh.write(f"{_frontend_build_mode(root)}\n")
    except OSError as exc:
        log_info(
            f"[Frontend] Could not record what the build was made for ({exc}); "
            f"the next start will rebuild.",
            COLOR_FRONTEND, 0,
        )


def _frontend_needs_build() -> bool:
    """The built frontend is missing or stale, and the source to fix it is here.

    Checked before npm is: a checkout whose dist/ is current must start without
    needing a toolchain, and only the build itself requires one.
    """
    if not os.path.isfile(os.path.join(_frontend_dir(), "package.json")):
        return False
    return _build_stamp_reason() is not None
