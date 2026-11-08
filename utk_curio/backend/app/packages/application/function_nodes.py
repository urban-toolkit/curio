"""The functions installed packages' modules offer: New node from a Python
function and the template that calls one (SCOUT's Compute Catalog, the Curio
way), what a node's code can call, as the header above its code lists it and
an agent that writes it reads it, and a package's, as its details list them.

Application layer of the packages package. A module is read, never imported
or run (``domain/function_nodes.py``): it offers what its ``__all__`` names,
followed through the imports from the other modules of its package. The
template written here is not installed here: the Node Catalog's dialog adds it
to a package the way Save as package node does (``/factory/install``). A
template written into another package than the function's names the
function's package in ``dependencies.packages``, so its node can import the
function (``python_modules.modules_for_node``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from utk_curio.backend.app.agents.domain import node_functions as curio_functions_page
from utk_curio.backend.app.execution import code_references
from utk_curio.backend.app.packages.application import python_modules as packages_python_modules
from utk_curio.backend.app.packages.application import template_packages as packages_template_packages
from utk_curio.backend.app.packages.application import templates as packages_templates
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.domain.function_nodes import (
    DEFAULT,
    FIXED,
    INPUT,
    USES,
    WIDGET,
    FunctionSignature,
    FunctionSourceError,
    read_function,
    read_functions,
    suggest_widget,
    suggested_use,
    template_code,
    template_description,
    widget_label,
)
from utk_curio.backend.app.packages.domain.manifest import ManifestError, PackageManifest
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.python_modules import module_files
from utk_curio.backend.app.packages.repositories.store import list_user_packages, package_dir

log = logging.getLogger(__name__)

#: At most this many module files of one package are read.
MAX_MODULE_FILES = 200

#: A module file larger than this is not read.
MAX_SOURCE_BYTES = 1_000_000

#: The port types a Python Computation node takes and gives
#: (``curio.builtin/python-computation``).
PORT_TYPES = ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON", "RASTER"]


def _read_source(path: Path, module: str) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise FunctionSourceError(f"{module} is larger than {MAX_SOURCE_BYTES:,} bytes, so it is not read.")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise FunctionSourceError(f"{module} is not UTF-8 text.") from None


class PackageModules:
    """The modules of the package at *package_root*, read for the functions
    they offer: each module's source is read once, and a module follows the
    names its ``__all__`` imports from the package's other modules
    (``read_functions``'s lookup)."""

    def __init__(self, package_root: Path, manifest: PackageManifest):
        self.files = module_files(package_root, manifest)
        self._paths = dict(self.files)
        self._texts: dict[str, str | Exception] = {}

    def __contains__(self, module: str) -> bool:
        return module in self._paths

    def _text(self, module: str) -> str | Exception:
        if module not in self._texts:
            try:
                self._texts[module] = _read_source(self._paths[module], module)
            except (FunctionSourceError, OSError) as exc:
                self._texts[module] = exc
        return self._texts[module]

    def _is_package(self, module: str) -> bool:
        return self._paths[module].name == "__init__.py"

    def lookup(self, module: str) -> tuple[str, bool] | None:
        """``(source, is a package's __init__.py)`` of a module the package ships, else None."""
        if module not in self._paths:
            return None
        text = self._text(module)
        return None if isinstance(text, Exception) else (text, self._is_package(module))

    def functions(self, module: str) -> list[FunctionSignature]:
        """What *module* offers. Raises ``FunctionSourceError`` or ``OSError``
        when it cannot be read, as ``read_functions`` does on one that does not parse."""
        text = self._text(module)
        if isinstance(text, Exception):
            raise text
        return read_functions(text, module, package=self._is_package(module), lookup=self.lookup)

    def function(self, module: str, name: str) -> FunctionSignature:
        """The function *name* *module* offers, one a node can call (``read_function``)."""
        text = self._text(module)
        if isinstance(text, Exception):
            raise text
        return read_function(text, module, name, package=self._is_package(module), lookup=self.lookup)

    def offered(self, names: frozenset[str] | None = None) -> list[tuple[str, str | None, list[FunctionSignature]]]:
        """``(module, problem, functions)`` for each module, in module order, at
        most MAX_MODULE_FILES of them; with *names*, those whose top-level name
        is one of them. A module that cannot be read carries its problem and no
        functions."""
        out: list[tuple[str, str | None, list[FunctionSignature]]] = []
        for module, _path in self.files[:MAX_MODULE_FILES]:
            if names is not None and module.split(".", 1)[0] not in names:
                continue
            try:
                out.append((module, None, self.functions(module)))
            except (FunctionSourceError, OSError) as exc:
                out.append((module, str(exc), []))
        return out


def _function_entry(signature: FunctionSignature) -> dict:
    entry = signature.to_json()
    for row, param in zip(entry["parameters"], signature.parameters):
        # A parameter's widget takes its name, and no widget takes the name of
        # one of the node's inputs, input_<k> or inputs (the Widgets tab's
        # check): such a parameter is offered no widget.
        takes_widget = code_references.widget_name_problem(param.name) is None
        row["widget"] = suggest_widget(param) if takes_widget else None
        row["use"] = suggested_use(param, takes_widget)
    return entry


def package_functions(user_key: str) -> list[dict]:
    """Every package in *user_key*'s store that ships modules, with the
    functions each module offers, their parameters, and the widget and use
    each parameter suggests. A module that does not parse carries its problem."""
    out: list[dict] = []
    with package_seed_lock(user_key):
        for root in list_user_packages(user_key):
            try:
                manifest = load_package_manifest(root)
            except ManifestError:
                continue
            modules = PackageModules(root, manifest)
            if not modules.files:
                continue
            out.append({
                "dirName": manifest.dir_name,
                "packageId": manifest.package_id,
                "major": manifest.major,
                "name": manifest.name,
                "readOnly": manifest.read_only,
                "modules": [
                    {"module": module, "problem": problem, "functions": [_function_entry(f) for f in functions]}
                    for module, problem, functions in modules.offered()
                ],
            })
    return out


def _read_row(function: FunctionSignature) -> dict:
    """A function as an agent reads it: its call and its docstring's first paragraph."""
    return {"name": function.name, "call": function.call, "doc": function.doc}


def module_functions(package_root: Path, manifest: PackageManifest, names: frozenset[str] | None = None) -> list[dict]:
    """Each module of the package at *package_root*, with the functions it
    offers (its ``__all__``, else its public functions), as an agent reads
    them: ``{"module", "problem", "functions": [{"name", "call", "doc"}]}``,
    in module order, each function's ``call`` its signature and its ``doc``
    its docstring's first paragraph. With *names*, only the modules whose
    top-level name is one of them. A module that does not parse carries its
    problem and no functions. Called under the store lock, as
    :func:`package_functions` reads."""
    return [
        {"module": module, "problem": problem, "functions": [_read_row(f) for f in functions]}
        for module, problem, functions in PackageModules(package_root, manifest).offered(names)
    ]


def _node_modules(
    user_key: str, node_type: object, project_id: str | None, owners=None,
) -> list[tuple[str, str, str | None, list[FunctionSignature]]]:
    """``(package, module, problem, functions)`` for each module the sandbox
    makes importable for a node of *node_type* (``python_modules.modules_for_node``,
    with *owners* as a run of an editor the dataflow's owner invited gets
    them), its own package's first."""
    sources = packages_python_modules.modules_for_node(user_key, node_type, project_id, owners=owners)
    if isinstance(sources, dict):
        sources = [sources]
    if not sources:
        return []
    # The store the run reads them from: the dataflow owner's, for a package she put in it.
    store_key = packages_python_modules._store_of_node(user_key, node_type, project_id, owners)
    out: list[tuple[str, str, str | None, list[FunctionSignature]]] = []
    with package_seed_lock(store_key):
        for source in sources:
            root = Path(source["root"]).parent
            try:
                manifest = load_package_manifest(root)
            except ManifestError:
                continue
            for module, problem, functions in PackageModules(root, manifest).offered(frozenset(source.get("names") or ())):
                out.append((manifest.dir_name, module, problem, functions))
    return out


def node_functions(user_key: str, node_type: object, project_id: str | None = None, *, owners=None) -> list[dict]:
    """The functions the code of a node of *node_type* can import: those the
    modules the sandbox makes importable for it offer
    (``python_modules.modules_for_node``), its own package's and those of the
    packages it names in ``dependencies.packages``. One ``{"package",
    "module", "problem", "functions"}`` per module, its own package's first.
    Empty for a built-in node and for a package that ships no modules."""
    return [
        {"package": package, "module": module, "problem": problem, "functions": [_read_row(f) for f in functions]}
        for package, module, problem, functions in _node_modules(user_key, node_type, project_id, owners)
    ]


def _curio_call(function) -> str:
    """A call of one of Curio's functions node code can start from: the
    arguments a call must give, a keyword-only one as ``name=name``."""
    parts = [
        f"{argument.name}={argument.name}" if argument.keyword_only else argument.name
        for argument in function.arguments
        if argument.default is None
    ]
    return f"{function.name}({', '.join(parts)})"


def _curio_functions(engine: str) -> list[dict]:
    """Curio's functions for node code in *engine*, from the page that lists
    them (``skills/node-functions/SKILL.md``, read by
    ``agents/domain/node_functions.py``), as a node's header lists them."""
    try:
        functions = curio_functions_page.for_engine(engine)
    except (curio_functions_page.NodeFunctionsError, OSError) as exc:
        log.warning("Curio's functions for node code could not be read: %s", exc)
        return []
    return [
        {"name": f.name, "call": f.call, "doc": f.does, "insert": _curio_call(f)}
        for f in functions
    ]


def functions_on_the_node(user_key: str, node_type: object, project_id: str | None = None, *, owners=None) -> dict:
    """What the code of a node of *node_type* can call, as the header above it
    lists it: ``{"engine", "curio", "modules"}``.

    *engine* is the engine of the node's template (``python`` or
    ``javascript``), from the store its run reads (``python_modules.node_template``);
    None, with nothing listed, for a node that holds no code. *curio* is
    Curio's functions for that engine (:func:`_curio_functions`). *modules*
    is, for a Python node, :func:`node_functions`'s modules that offer a
    function or carry a problem, its own package's first. Each function is
    ``{"name", "call", "doc", "insert"}``: its signature, the first paragraph
    of its docstring, and the call a click on it writes."""
    template = packages_python_modules.node_template(user_key, node_type, project_id, owners=owners)
    code = template is not None and packages_templates.template_content_kind(template) == packages_templates.CONTENT_KIND_CODE
    engine = template.engine if code else None
    if engine not in curio_functions_page.ENGINES:
        return {"engine": None, "curio": [], "modules": []}
    modules: list[dict] = []
    if engine == "python":
        for package, module, problem, functions in _node_modules(user_key, node_type, project_id, owners):
            if functions or problem:
                modules.append({
                    "package": package, "module": module, "problem": problem,
                    "functions": [{**_read_row(f), "insert": f.required_call} for f in functions],
                })
    return {"engine": engine, "curio": _curio_functions(engine), "modules": modules}


def package_modules_functions(user_key: str, dir_name: str) -> dict:
    """``{"dirName", "modules"}``: the functions each module of the package
    *dir_name* offers (:func:`module_functions`), as its details list them:
    *user_key*'s copy, else the catalog's. A 404 for a package neither holds."""
    if not PACKAGE_DIR_RE.match(str(dir_name)):
        raise PackageServiceError(f"no package {dir_name!r}", 404)
    own = package_dir(user_key, dir_name)
    with package_seed_lock(user_key):
        if own.is_dir():
            return {"dirName": dir_name, "modules": module_functions(own, load_package_manifest(own))}
    shipped = packages_catalog_dir.catalog_root() / dir_name
    if shipped.is_dir():
        return {"dirName": dir_name, "modules": module_functions(shipped, load_package_manifest(shipped))}
    raise PackageServiceError(f"no package {dir_name!r}", 404)


def _module_function(user_key: str, dir_name: str, module: str, function: str) -> tuple[PackageManifest, FunctionSignature]:
    """The function *function* the module *module* of *user_key*'s package
    *dir_name* offers, read again from the store, and the package's manifest."""
    root = package_dir(user_key, dir_name)
    with package_seed_lock(user_key):
        if not root.is_dir():
            raise PackageServiceError(f"package {dir_name} is not installed", 404)
        manifest = load_package_manifest(root)
        modules = PackageModules(root, manifest)
        if module not in modules:
            raise PackageServiceError(f"package {dir_name} ships no module named {module!r}", 404)
        try:
            return manifest, modules.function(module, function)
        except FunctionSourceError as exc:
            raise PackageServiceError(str(exc)) from None


def _widget(param_name: str, raw: object, others: list[dict]) -> dict:
    if not isinstance(raw, dict) or raw.get("name") != param_name:
        raise PackageServiceError(f"The widget for {param_name} must be named {param_name}.")
    widget = {key: raw[key] for key in ("name", "type", "label", "default", "options") if key in raw}
    if not str(widget.get("label") or "").strip():
        widget.pop("label", None)
    problem = code_references.check_widget_def(widget, others)
    if problem:
        raise PackageServiceError(f"The widget for {param_name}: {problem}")
    return widget


def _uses(signature: FunctionSignature, bindings: dict) -> tuple[dict, list[dict], int]:
    """Each parameter's use, checked; the widgets; and how many inputs, which
    are numbered in parameter order."""
    known = {param.name for param in signature.parameters}
    unknown = sorted(set(bindings) - known)
    if unknown:
        raise PackageServiceError(f"{signature.name} has no parameter named {unknown[0]}.")
    uses: dict[str, dict] = {}
    widgets: list[dict] = []
    inputs = 0
    for param in signature.parameters:
        raw = bindings.get(param.name)
        how = raw.get("use") if isinstance(raw, dict) else None
        if how not in USES:
            raise PackageServiceError(
                f"Choose what {param.name} is given: a widget, a value, an input or its default."
            )
        if how == WIDGET:
            widgets.append(_widget(param.name, raw.get("widget"), widgets))
            uses[param.name] = {"use": WIDGET}
        elif how == INPUT:
            uses[param.name] = {"use": INPUT, "slot": inputs}
            inputs += 1
        elif how == FIXED:
            uses[param.name] = {"use": FIXED, "value": raw.get("value")}
        else:
            uses[param.name] = {"use": DEFAULT}
    return uses, widgets, inputs


def write_function_template(
    user_key: str, dir_name: str, module: str, function: str, label: str | None, bindings: dict,
) -> dict:
    """The template of a node that calls *function* from *module*, a module the
    package *dir_name* in *user_key*'s store ships, with each parameter given
    what *bindings* says.

    Returns ``{"template", "source", "package", "dependency"}``: the manifest
    entry (its widgets included), its source file, the function's package,
    and the ``dependencies.packages`` entry a template in another package
    needs. The module is read again here: nothing about the function is
    taken from the request.
    """
    manifest, signature = _module_function(user_key, dir_name, module, function)
    try:
        uses, widgets, inputs = _uses(signature, bindings)
        code = template_code(module, signature, uses)
    except FunctionSourceError as exc:
        raise PackageServiceError(str(exc)) from None
    label = (label or "").strip() or widget_label(function)
    template_id = (
        packages_template_packages.template_slug(label)
        or packages_template_packages.template_slug(function)
        or "function"
    )
    filename = f"{template_id}.py"
    template: dict = {
        "id": template_id,
        "label": label,
        "category": "computation",
        "engine": "python",
        "editor": "code",
        "behavior": "code",
        "iconRef": "fa-brands:python",
        "description": template_description(module, signature),
        "hasCode": True,
        "hasWidgets": True,
        "hasGrammar": False,
        "inputPorts": [{"types": list(PORT_TYPES), "cardinality": str(inputs)}] if inputs else [],
        "outputPorts": [{"types": list(PORT_TYPES), "cardinality": "[1,n]"}],
        "source": f"sources/{filename}",
    }
    if widgets:
        template["widgets"] = widgets
    return {
        "template": template,
        "source": {"filename": filename, "code": code},
        "package": {
            "dirName": manifest.dir_name,
            "packageId": manifest.package_id,
            "major": manifest.major,
            "readOnly": manifest.read_only,
        },
        "dependency": {manifest.dir_name: "*"},
    }
