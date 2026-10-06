"""New node from a Python function: the functions installed packages' modules
define, and the template that calls one (SCOUT's Compute Catalog, the Curio way).

Application layer of the packages package. A module is read, never imported
or run (``domain/function_nodes.py``). The template written here is not
installed here: the Node Catalog's dialog adds it to a package the way Save as
package node does (``/factory/install``). A template written into another
package than the function's names the function's package in
``dependencies.packages``, so its node can import the function
(``python_modules.modules_for_node``).
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.execution import code_references
from utk_curio.backend.app.packages.application import template_packages as packages_template_packages
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
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.python_modules import module_files
from utk_curio.backend.app.packages.repositories.store import list_user_packages, package_dir

#: At most this many module files of one package are read.
MAX_MODULE_FILES = 200

#: A module file larger than this is not read.
MAX_SOURCE_BYTES = 1_000_000

#: The port types a Python Computation node takes and gives
#: (``curio.builtin/computation-analysis``).
PORT_TYPES = ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON", "RASTER"]


def _read_source(path: Path, module: str) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise FunctionSourceError(f"{module} is larger than {MAX_SOURCE_BYTES:,} bytes, so it is not read.")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise FunctionSourceError(f"{module} is not UTF-8 text.") from None


def _function_entry(signature: FunctionSignature) -> dict:
    entry = signature.to_json()
    for row, param in zip(entry["parameters"], signature.parameters):
        row["widget"] = suggest_widget(param)
        row["use"] = suggested_use(param)
    return entry


def _module_entry(module: str, path: Path) -> dict:
    try:
        functions = read_functions(_read_source(path, module), module)
    except (FunctionSourceError, OSError) as exc:
        return {"module": module, "problem": str(exc), "functions": []}
    return {"module": module, "problem": None, "functions": [_function_entry(f) for f in functions]}


def package_functions(user_key: str) -> list[dict]:
    """Every package in *user_key*'s store that ships modules, with each
    module's public functions, their parameters, and the widget and use each
    parameter suggests. A module that does not parse carries its problem."""
    out: list[dict] = []
    with package_seed_lock(user_key):
        for root in list_user_packages(user_key):
            try:
                manifest = load_package_manifest(root)
            except ManifestError:
                continue
            files = module_files(root, manifest)[:MAX_MODULE_FILES]
            if not files:
                continue
            out.append({
                "dirName": manifest.dir_name,
                "packageId": manifest.package_id,
                "major": manifest.major,
                "name": manifest.name,
                "readOnly": manifest.read_only,
                "modules": [_module_entry(module, path) for module, path in files],
            })
    return out


def _module_source(user_key: str, dir_name: str, module: str) -> tuple[PackageManifest, str]:
    root = package_dir(user_key, dir_name)
    with package_seed_lock(user_key):
        if not root.is_dir():
            raise PackageServiceError(f"package {dir_name} is not installed", 404)
        manifest = load_package_manifest(root)
        path = dict(module_files(root, manifest)).get(module)
        if path is None:
            raise PackageServiceError(f"package {dir_name} ships no module named {module!r}", 404)
        try:
            return manifest, _read_source(path, module)
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
    manifest, source = _module_source(user_key, dir_name, module)
    try:
        signature = read_function(source, module, function)
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
