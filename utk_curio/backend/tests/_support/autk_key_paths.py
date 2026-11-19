"""The keys of the vendored Autark grammar schema, by path, and the keys a
document writes, by the same paths.

A path names each property from the document down, a dot before each:
``map[].layerRefs[].pointSize``. ``[]`` follows a list, and a section written
as one object or as a list of them (``map``, ``plot``) is written as a list. A
list whose items are kinds told apart by a constant, their ``type`` or
``mark``, names the kind in the brackets (``data[heatmap].grid.rows``,
``plot[scatter].axis``), and so does an object of such kinds, in parentheses
(``compute[render].aggregation(objects)``); the kind alone is a path of its
own, and the constant is left out of the kind's keys where the kind requires
it (``compute[gpgpu].type`` is a key: a GPGPU pass may leave it out). A kind
whose constant takes several values is a path for each value, its keys named
once with the values joined (``plot[line]``, ``plot[linechart]``,
``plot[line|linechart].axis``). A map of names to values (a pass's
``uniforms``) is ``*``. A key the schema forbids in one form of an object
(``"not": {}``) is not a key of that form.

``utk_curio/backend/tests/autk_grammar_key_tests.json`` names the test that
runs each path, and ``test_agents/test_autk_every_key_tested.py`` checks it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

#: The keys whose constant tells the kinds of a list or an object apart.
DISCRIMINATORS = ("type", "mark")

AUTK_TYPE = "curio.builtin/autk-grammar"


class _Schema:
    def __init__(self, schema: dict):
        self.defs = schema.get("definitions") or schema.get("$defs") or {}

    def resolve(self, node, seen: frozenset):
        while isinstance(node, dict) and "$ref" in node:
            name = unquote(node["$ref"].rsplit("/", 1)[-1])
            if name in seen:
                return None, seen
            seen = seen | {name}
            node = self.defs.get(name)
        return node, seen

    def forms(self, node, seen: frozenset) -> list:
        """The schemas a value at *node* can take, through ``$ref``, ``anyOf``,
        ``oneOf`` and the ``then`` of each if/then of an ``allOf``, each with
        the definitions met on the way (so a definition that holds itself,
        GeoJSON's geometry collection, is walked once)."""
        node, seen = self.resolve(node, seen)
        if not isinstance(node, dict):
            return []
        alternatives = [*node.get("anyOf", []), *node.get("oneOf", [])]
        alternatives += [c["then"] for c in node.get("allOf", []) if isinstance(c, dict) and "then" in c]
        if not alternatives:
            return [(node, seen)]
        return [form for alternative in alternatives for form in self.forms(alternative, seen)]

    @staticmethod
    def is_list(form: dict) -> bool:
        return isinstance(form.get("items"), dict)

    @staticmethod
    def is_object(form: dict) -> bool:
        return isinstance(form.get("properties"), dict) or isinstance(form.get("additionalProperties"), dict)

    @staticmethod
    def kind(form: dict):
        """The discriminator of *form* and the values it takes, or (None, [])."""
        for key in DISCRIMINATORS:
            prop = (form.get("properties") or {}).get(key)
            if not isinstance(prop, dict):
                continue
            if "const" in prop:
                return key, [str(prop["const"])]
            if isinstance(prop.get("enum"), list):
                return key, [str(value) for value in prop["enum"]]
        return None, []

    def shapes(self, node, seen: frozenset):
        """What a value at *node* holds: the lists of lists it can be, the
        object forms it or its items can be, and whether those are items."""
        found = self.forms(node, seen)
        lists = [(form, s) for form, s in found if self.is_list(form)]
        objects = [(form, s) for form, s in found if self.is_object(form)]
        if not lists:
            return [], objects, False
        nested, items = [], []
        for form, s in lists:
            for inner, inner_seen in self.forms(form["items"], s):
                if self.is_list(inner):
                    nested.append((inner, inner_seen))
                elif self.is_object(inner):
                    items.append((inner, inner_seen))
        unique = []
        for form, s in items + objects:
            if all(form is not held for held, _ in unique):
                unique.append((form, s))
        return nested, unique, True

    def branches(self, objects: list, path: str, in_list: bool):
        """Each object form, with the path its keys are written under, its kind
        (discriminator and values) when the forms are kinds, and the paths of
        its kinds."""
        kinds = [self.kind(form) for form, _ in objects]
        told_apart = all(key for key, _ in kinds) and len({tuple(values) for _, values in kinds}) > 1
        for (form, s), (key, values) in zip(objects, kinds):
            if not told_apart:
                yield form, s, (f"{path}[]" if in_list else path), None, []
                continue
            tag = "|".join(values)
            here = f"{path}[{tag}]" if in_list else f"{path}({tag})"
            yield form, s, here, (key, values), [
                f"{path}[{value}]" if in_list else f"{path}({value})" for value in values
            ]


def key_paths(schema: dict) -> list[str]:
    """Every key path *schema* lets a document write, in the schema's order."""
    walker = _Schema(schema)
    paths: list[str] = []

    def emit(path: str) -> None:
        if path not in paths:
            paths.append(path)

    def walk(node, path: str, seen: frozenset) -> None:
        nested, objects, in_list = walker.shapes(node, seen)
        for form, s in nested:
            walk(form, path + "[]", s)
        for form, s, here, told, kinds in walker.branches(objects, path, in_list):
            for kind in kinds:
                emit(kind)
            required = set(form.get("required") or [])
            for name, sub in (form.get("properties") or {}).items():
                if isinstance(sub, dict) and sub.get("not") == {}:
                    continue
                if told and name == told[0] and name in required:
                    continue
                child = f"{here}.{name}" if here else name
                emit(child)
                walk(sub, child, s)
            free = form.get("additionalProperties")
            if isinstance(free, dict) and free:
                walk(free, f"{here}.*", s)

    walk({"$ref": schema["$ref"]}, "", frozenset())
    return paths


def written_paths(schema: dict, document) -> set[str]:
    """The key paths *document* writes, named as :func:`key_paths` names them.
    A key the schema does not know is left out."""
    walker = _Schema(schema)
    found: set[str] = set()

    def walk(node, value, path: str, seen: frozenset) -> None:
        nested, objects, in_list = walker.shapes(node, seen)
        for item in (value if in_list and isinstance(value, list) else [value]):
            if isinstance(item, list):
                for form, s in nested:
                    walk(form, item, path + "[]", s)
                continue
            if not isinstance(item, dict):
                continue
            branches = list(walker.branches(objects, path, in_list))
            told = [branch for branch in branches if branch[3]]
            if told:
                key = told[0][3][0]
                written = item.get(key)
                if written is None:
                    # A kind that may leave its constant out is the one meant.
                    branches = [b for b in told if key not in set(b[0].get("required") or [])]
                else:
                    branches = [b for b in told if str(written) in b[3][1]]
            for form, s, here, kind, kinds in branches:
                if kind:
                    written = item.get(kind[0])
                    found.update(k for k in kinds if written is None or k.endswith((f"[{written}]", f"({written})")))
                properties = form.get("properties") or {}
                required = set(form.get("required") or [])
                free = form.get("additionalProperties")
                for name, sub in item.items():
                    if name in properties:
                        if kind and name == kind[0] and name in required:
                            continue
                        child = f"{here}.{name}" if here else name
                        found.add(child)
                        walk(properties[name], sub, child, s)
                    elif isinstance(free, dict) and free:
                        walk(free, sub, f"{here}.*", s)

    walk({"$ref": schema["$ref"]}, document, "", frozenset())
    return found


_CHIP = re.compile(r"\[!!\s*(.*?)\s*!!\]")


def _parsed(code: str):
    try:
        return json.loads(code)
    except ValueError:
        try:
            return json.loads(_CHIP.sub(lambda chip: json.dumps(chip.group(1)), code))
        except ValueError:
            return None


def documents_in(path: Path) -> list:
    """The Autark documents a JSON file holds: a dataflow's, the code of each
    of its Autark nodes; any other file's, each object written under a key
    named ``spec`` or ``document``, however deep."""
    held = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(held, dict) and isinstance((held.get("dataflow") or held).get("nodes"), list):
        nodes = (held.get("dataflow") or held)["nodes"]
        documents = [_parsed(node.get("content") or "") for node in nodes if node.get("type") == AUTK_TYPE]
        return [document for document in documents if isinstance(document, dict)]
    documents: list = []

    def collect(value) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("spec", "document") and isinstance(inner, dict):
                    documents.append(inner)
                else:
                    collect(inner)
        elif isinstance(value, list):
            for inner in value:
                collect(inner)

    collect(held)
    return documents
