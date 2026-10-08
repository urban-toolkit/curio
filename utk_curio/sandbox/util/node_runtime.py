"""How Curio runs autk-db in Node, shared by every caller.

The launcher (``cli/dependencies.py::_ensure_root_node_modules``) installs the
sandbox's Node.js packages in the folder :func:`nodejs_dir` names, and the
sandbox's JS nodes (``app/worker.py::execute_js_code``) and the Discovery
Catalog's OpenStreetMap loader (``backend/app/discovery/providers/autark_osm.py``)
run Node against that folder's ``node_modules`` and identify themselves to
Overpass the same way.
"""

import json
import os
import pathlib

#: The folder that holds ``utk_curio/``: the repository root in a clone, the
#: Docker image and CI; site-packages in a pip install.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: The files that name the Node.js packages the sandbox runs.
PACKAGE_FILES = ('package.json', 'package-lock.json')

#: Where the pip package carries the repository's ``PACKAGE_FILES`` (``setup.py``
#: copies them there), under the folder that holds ``utk_curio/``.
SHIPPED_PACKAGE_FILES = pathlib.PurePosixPath('utk_curio', 'sandbox', 'nodejs')

#: The folder of Curio's state directory where a pip install keeps the
#: sandbox's Node.js packages.
NODEJS_FOLDER = 'nodejs'

AUTK_DB = '@urban-toolkit/autk-db'

#: What every Overpass request from Curio's Node processes says it is. The
#: Overpass usage policy asks a client to identify itself.
OVERPASS_USER_AGENT = 'Curio (https://curio.urbantk.org) autk-db'


def is_curio_package_json(path):
    """Whether *path* is a package.json of Curio's own: named ``curio``, with
    autk-db among its dependencies."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    dependencies = data.get('dependencies')
    return data.get('name') == 'curio' and isinstance(dependencies, dict) and AUTK_DB in dependencies


def state_dir():
    """Curio's state directory: ``CURIO_STATE_DIR``, or ``.curio`` in the
    folder Curio was started from (``CURIO_LAUNCH_CWD``)."""
    override = os.environ.get('CURIO_STATE_DIR')
    if override:
        return pathlib.Path(override)
    return pathlib.Path(os.environ.get('CURIO_LAUNCH_CWD') or os.getcwd()) / '.curio'


def nodejs_dir(root=None):
    """The folder that holds Curio's package.json for the sandbox's Node.js
    packages, and their ``node_modules``.

    *root* is the folder that holds ``utk_curio/`` (``REPO_ROOT`` when None):
    that folder when it holds Curio's package.json (a clone, the Docker image,
    CI), else ``nodejs/`` in Curio's state directory (a pip install).
    """
    root = pathlib.Path(REPO_ROOT if root is None else root)
    if is_curio_package_json(root / 'package.json'):
        return root
    return state_dir() / NODEJS_FOLDER


def node_modules_dir(root=None):
    """The ``node_modules`` the sandbox's Node.js packages are installed in."""
    return nodejs_dir(root) / 'node_modules'


def node_env(base=None, node_modules=None):
    """The environment for a Node child: *base* (default ``os.environ``), with
    *node_modules* (default :func:`node_modules_dir`) first on ``NODE_PATH``.

    ``NODE_PATH`` is consulted only by the CommonJS ``require()`` resolver, not
    by ESM, so it does not resolve a top-level autk-db import (callers rewrite
    that to an absolute file URL with ``resolve_pkg_entry_url``). It still helps
    any CJS ``require()`` autk-db's worker threads perform.
    """
    env = dict(os.environ if base is None else base)
    node_modules = pathlib.Path(node_modules) if node_modules is not None else node_modules_dir()
    if node_modules.is_dir():
        existing = env.get('NODE_PATH', '')
        env['NODE_PATH'] = str(node_modules) + (os.pathsep + existing if existing else '')
    return env


# Conditions a dynamic ``import()`` in Node matches, see _pick_export_entry.
_ACTIVE_CONDITIONS = ('node', 'import', 'default')
# Not conditions Node resolves an ``import()`` with, but where a package with no
# active one keeps its entry; tried only after every active condition failed.
_FALLBACK_CONDITIONS = ('module', 'require')


def _pick_export_entry(node):
    """Resolve a package.json ``exports`` subtree down to a relative path string.

    Node's export conditions NEST: ``exports["."]["import"]`` is frequently
    another condition object (``{"types": ..., "default": "./x.mjs"}``) rather
    than a path. Walking only one level and handing the resulting dict to
    ``pathlib`` raises TypeError, which the caller used to swallow - silently
    degrading to the bare specifier, which then resolves only when the Node
    subprocess cwd happens to sit inside the repo.

    The pick is Node's own: the first key, in the order the package lists
    them, that is a condition this import satisfies. The js_wrapper runs under
    ``--input-type=commonjs`` but reaches packages through dynamic ``import()``
    in Node, so ``node``, ``import`` and ``default`` are active. A fixed
    priority of our own picked ``import`` over ``node``, which for autk-db 3
    (``browser``, ``node``, ``import``, ``default``) is its browser build: it
    needs a ``Worker`` that Node does not have.
    """
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    for key, value in node.items():
        if key in _ACTIVE_CONDITIONS:
            entry = _pick_export_entry(value)
            if entry:
                return entry
    for key in _FALLBACK_CONDITIONS:
        if key in node:
            entry = _pick_export_entry(node[key])
            if entry:
                return entry
    return None


def resolve_pkg_entry_url(specifier, root_node_modules):
    """Map a bare package specifier to an absolute ``file://`` URL, or None.

    Returns None for anything that is not a bare specifier (relative, absolute,
    URL, ``node:`` builtin), for a package that isn't installed under
    ``root_node_modules``, or for an entry that escapes it.
    """
    import json
    import pathlib

    # Only bare specifiers (not relative / absolute / URL / node: builtin).
    if not specifier or specifier[0] in './' or ':' in specifier:
        return None
    root_node_modules = pathlib.Path(root_node_modules)
    seg = specifier.split('/')
    pkg = '/'.join(seg[:2]) if specifier.startswith('@') else seg[0]
    pkg_dir = root_node_modules / pkg
    pj = pkg_dir / 'package.json'
    if not pj.is_file():
        return None
    try:
        meta = json.loads(pj.read_text(encoding='utf-8'))
    except Exception:
        return None
    exp = meta.get('exports')
    entry = None
    if isinstance(exp, str):
        entry = exp
    elif isinstance(exp, dict):
        # A subpath map keys on "."; a bare condition map has no "." and applies
        # to the root itself.
        entry = _pick_export_entry(exp.get('.', exp))
    entry = entry or meta.get('module') or meta.get('main') or 'index.js'
    if not isinstance(entry, str):
        return None
    try:
        entry_path = (pkg_dir / entry).resolve()
    except Exception:
        return None
    if not entry_path.is_file() or root_node_modules.resolve() not in entry_path.parents:
        return None
    return entry_path.as_uri()
