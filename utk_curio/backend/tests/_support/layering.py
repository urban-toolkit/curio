"""The layering rule engine (memo dev/142 B5, shared by dev/143 §7).

A layered package — ``domain / repositories / infrastructure / application`` behind
one ``service.py`` facade, with presentation in ``routes/`` — is described by a
:class:`LayeredPackage` and checked by the rule functions below. Each suite
instantiates its own description and asserts the rules it needs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LayeredPackage:
    root: Path                       # the package directory
    base: str                        # its dotted import path
    may_import: dict[str, set[str]]  # layer -> layers it may reach (itself included)
    beside: set[str] = field(default_factory=set)      # subsystems beside the layers (may reach every layer; reached only by application)
    facade: str = "service.py"
    root_modules: tuple[str, ...] = ("__init__.py", "service.py")
    bounded_dirs: tuple[str, ...] = ("application",)   # where the 150-line bound applies
    lazy_allowed_outside: set[str] = field(default_factory=set)  # app-relative paths that may import the package lazily
    lazy_allowed_inside: set[str] = field(default_factory=set)   # dotted module prefixes a lazy import inside the package may name

    @property
    def app(self) -> Path:
        return self.root.parent

    def modules(self):
        for path in sorted(self.root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path, ast.parse(path.read_text(encoding="utf-8"))

    def heads_reached(self, module: str, names) -> set[str]:
        """The top-level directories an ``from <module> import <names>`` reaches inside the package."""
        if not module.startswith(self.base):
            return set()
        rest = module[len(self.base):].lstrip(".")
        heads = [rest.split(".")[0]] if rest else [n for n in names]
        return set(heads)


def downward_only_offenders(pkg: LayeredPackage) -> list[str]:
    layers = set(pkg.may_import)
    out = []
    for path, tree in pkg.modules():
        rel = path.relative_to(pkg.root).as_posix()
        mine = rel.split("/")[0]
        if mine in pkg.may_import:
            allowed = pkg.may_import[mine]
        elif mine in pkg.beside:
            allowed = layers | pkg.beside
        else:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                reached = pkg.heads_reached(node.module, [a.name for a in node.names]) & (layers | pkg.beside)
                for head in reached - allowed:
                    out.append(f"{rel}:{node.lineno} imports {head}")
    return out


def lazy_inside_offenders(pkg: LayeredPackage) -> list[str]:
    """In-function imports of the facade, ``application`` or a subsystem inside the package."""
    banned = [f"{pkg.base}.application", f"{pkg.base}.{pkg.facade[:-3]}"] + [f"{pkg.base}.{b}" for b in pkg.beside]
    out = []
    for path, tree in pkg.modules():
        rel = path.relative_to(pkg.root).as_posix()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module and node.col_offset > 0):
                continue
            if node.module == pkg.base or any(node.module == b or node.module.startswith(b + ".") for b in banned):
                out.append(f"{rel}:{node.lineno} {node.module}")
            elif node.module.startswith(pkg.base) and not any(node.module.startswith(a) for a in pkg.lazy_allowed_inside):
                out.append(f"{rel}:{node.lineno} {node.module}")
    return out


def lazy_outside_offenders(pkg: LayeredPackage) -> list[str]:
    out = []
    for path in sorted(pkg.app.rglob("*.py")):
        if pkg.root.name in path.relative_to(pkg.app).parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(pkg.app).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(pkg.base) and node.col_offset > 0:
                if rel not in pkg.lazy_allowed_outside:
                    out.append(f"{rel}:{node.lineno} {node.module}")
    return out


def facade_defines_nothing(pkg: LayeredPackage) -> bool:
    tree = ast.parse((pkg.root / pkg.facade).read_text(encoding="utf-8"))
    defined = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]
    return defined == [] and all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr)) for n in tree.body)


def oversize_functions(pkg: LayeredPackage, bound: int = 150) -> list[str]:
    out = []
    for path, tree in pkg.modules():
        rel = path.relative_to(pkg.root).as_posix()
        if rel.split("/")[0] not in pkg.bounded_dirs:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno + 1
                if length > bound:
                    out.append(f"{rel}::{node.name} ({length} lines)")
    return out


def root_modules(pkg: LayeredPackage) -> list[str]:
    return sorted(p.name for p in pkg.root.glob("*.py"))


def pure_layer_offenders(pkg: LayeredPackage, layer: str, allowed_prefixes: tuple[str, ...]) -> list[str]:
    """Modules of *layer* importing anything from the app outside *allowed_prefixes* (their own layer included by the caller)."""
    out = []
    for path, tree in pkg.modules():
        rel = path.relative_to(pkg.root).as_posix()
        if rel.split("/")[0] != layer:
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module: mods = [node.module]
            elif isinstance(node, ast.Import): mods = [a.name for a in node.names]
            for m in mods:
                if m.startswith("utk_curio") and not any(m.startswith(a) for a in allowed_prefixes):
                    out.append(f"{rel}:{node.lineno} {m}")
    return out
