"""How Curio runs autk-db in Node, shared by every caller.

The sandbox's JS nodes (``app/worker.py::execute_js_code``) and the Discovery
Catalog's OpenStreetMap loader (``backend/app/discovery/providers/autark_osm.py``)
both run Node against the repo-root ``node_modules``, so they resolve the same
autk-db build, and both identify themselves to Overpass the same way.
"""

import os
import pathlib

#: The repository root: ``utk_curio/sandbox/util/`` is three levels below it.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: The ``node_modules`` the root ``package.json`` installs autk-db into.
ROOT_NODE_MODULES = REPO_ROOT / 'node_modules'

#: What every Overpass request from Curio's Node processes says it is. The
#: Overpass usage policy asks a client to identify itself.
OVERPASS_USER_AGENT = 'Curio (https://github.com/urban-toolkit/curio) autk-db'


def node_env(base=None):
    """The environment for a Node child: *base* (default ``os.environ``), with
    ``ROOT_NODE_MODULES`` first on ``NODE_PATH``.

    ``NODE_PATH`` is consulted only by the CommonJS ``require()`` resolver, not
    by ESM, so it does not resolve a top-level autk-db import (callers rewrite
    that to an absolute file URL with ``resolve_pkg_entry_url``). It still helps
    any CJS ``require()`` autk-db's worker threads perform.
    """
    env = dict(os.environ if base is None else base)
    if ROOT_NODE_MODULES.is_dir():
        existing = env.get('NODE_PATH', '')
        env['NODE_PATH'] = str(ROOT_NODE_MODULES) + (os.pathsep + existing if existing else '')
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
