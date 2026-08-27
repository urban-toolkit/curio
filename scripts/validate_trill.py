#!/usr/bin/env python3
"""Validate dataflow (``.trill``) JSON files against ``docs/schemas/trill.v1.json``.

WHY
---
The trill format had no written contract until ``docs/schemas/trill.v1.json``.
``projects/storage.py`` reads and writes a spec as opaque JSON, and every reader
downstream is deliberately forgiving — a malformed node is skipped, not
reported. That tolerance is right for a running app and useless for finding out
which of your saved projects are stale.

CI covers the 31 specs committed under ``docs/examples/``. It cannot see your own
projects: ``.curio/`` is gitignored, so those 18-odd files exist only on your
machine. This script is the half that reaches them, which is what makes "all
dataflow jsons are checked against the schema" true rather than aspirational.

Expect your ``.curio`` projects to report failures. They are a genuinely looser
dialect — saved before the schema existed, often missing ``provenance_id`` or
``timestamp``, and mixing versioned (``curio.builtin/vis-vega@1``) with
unversioned node types. That report is the point: it is the migration triage
``docs/NODE-CATALOG.md`` asks for when it says legacy projects need a one-time
JSON rewrite. A non-zero exit from ``--all`` is information, not a broken build.

What this does NOT check is whether a node's ``type`` resolves to a template
that actually exists. Nodes are defined by package manifests, so resolution
depends on which packages are installed; the schema validates only the shape of
the coordinate. Pass ``--resolve`` to additionally check every node type against
the manifests under ``packages/``.

HOW
---
    python scripts/validate_trill.py docs/examples/01-vega-lite-chained-transforms.json
    python scripts/validate_trill.py docs/examples/           # a directory, recursively
    python scripts/validate_trill.py --all                    # examples + your .curio projects
    python scripts/validate_trill.py --all --resolve          # also check node types resolve
    python scripts/validate_trill.py --all --quiet            # exit code only

Exit code is 0 when every file validated, 1 when any file failed, and 2 on a
usage problem such as an unreadable path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from utk_curio.backend.app.packages.spec_packages import (  # noqa: E402
    unversioned_node_type,
)

SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "trill.v1.json"
DEFAULT_MAX_ERRORS = 5


def _load_schema() -> Draft202012Validator:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return Draft202012Validator(json.load(fh))


def _template_index() -> dict[str, dict]:
    """Map ``<packageId>/<templateId>`` to its template, from ``packages/``.

    The in-repo catalog, not a user store: that is what makes a bundled but
    not-auto-installed package such as ``curio.streetvision`` resolvable.
    """
    index: dict[str, dict] = {}
    for manifest_path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        try:
            with manifest_path.open(encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        package_id = manifest.get("id")
        if not isinstance(package_id, str):
            continue
        for template in manifest.get("templates") or []:
            if isinstance(template, dict) and isinstance(template.get("id"), str):
                index[f"{package_id}/{template['id']}"] = template
    return index


# ---------------------------------------------------------------------------
# Corpora
# ---------------------------------------------------------------------------

def _corpora() -> list[tuple[str, list[Path]]]:
    """The three places trill files live, in the order worth reporting them."""
    examples = REPO_ROOT / "docs" / "examples"
    return [
        ("docs/examples", sorted(examples.glob("*.json"))),
        ("docs/examples/dataflows", sorted((examples / "dataflows").glob("*.json"))),
        (
            ".curio user projects",
            sorted((REPO_ROOT / ".curio" / "users").glob("*/projects/*/spec.trill.json")),
        ),
    ]


# Filenames under .curio/ and packages/ that are JSON but emphatically not
# dataflows. Without this list, pointing the script at .curio/ reports every
# package, agent, and dataset manifest as "missing 'dataflow'" — noise that
# buries the real findings.
_NOT_TRILL = {
    "manifest.json",
    "integrity.json",
    "default-packages.json",
    ".seed-state.json",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
}


def _looks_like_trill(path: Path) -> bool:
    """Is this file worth validating as a dataflow?

    A named file is always validated — asking about a specific path deserves a
    verdict, including "this is not a dataflow at all". Directory scans need a
    filter, so a file qualifies on its name (``*.trill.json``) or on carrying a
    top-level ``dataflow`` key. Deliberately not "has a dataflow key" alone: a
    trill file broken badly enough to have lost that key is exactly what someone
    running this wants told about, and the name still identifies it.
    """
    if path.name in _NOT_TRILL:
        return False
    if path.name.endswith(".trill.json"):
        return True
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(doc, dict) and "dataflow" in doc


def _files_under(target: Path) -> list[Path]:
    if not target.is_dir():
        return [target]
    # Skip docs/examples/data — dataset fixtures, not dataflows.
    return sorted(
        p
        for p in target.rglob("*.json")
        if p.parent.name != "data" and _looks_like_trill(p)
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _describe(error) -> str:
    where = ".".join(str(part) for part in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"


def _validate_one(
    path: Path,
    validator: Draft202012Validator,
    templates: dict[str, dict] | None,
    max_errors: int,
    quiet: bool,
) -> int:
    """Report on one file. Returns 0 when it validated, 1 otherwise."""
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        if not quiet:
            print(f"  FAIL {_rel(path)}\n    not valid JSON: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        if not quiet:
            print(f"  FAIL {_rel(path)}\n    unreadable: {exc}", file=sys.stderr)
        return 1

    problems = [
        _describe(err)
        for err in sorted(
            validator.iter_errors(doc),
            key=lambda e: [str(p) for p in e.absolute_path],
        )
    ]

    if templates is not None:
        flow = doc.get("dataflow") if isinstance(doc, dict) else None
        nodes = (flow or {}).get("nodes") or []
        unresolved = sorted(
            {
                node.get("type")
                for node in nodes
                if isinstance(node, dict)
                and unversioned_node_type(node.get("type", "")) not in templates
            }
        )
        problems += [
            f"dataflow.nodes: node type {t!r} has no template under packages/"
            for t in unresolved
        ]

    if not problems:
        if not quiet:
            print(f"  ok   {_rel(path)}")
        return 0

    if not quiet:
        print(f"  FAIL {_rel(path)}  ({len(problems)} problem(s))", file=sys.stderr)
        for line in problems[:max_errors]:
            print(f"    {line}", file=sys.stderr)
        if len(problems) > max_errors:
            print(
                f"    ... and {len(problems) - max_errors} more "
                f"(raise --max-errors to see them)",
                file=sys.stderr,
            )
    return 1


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate trill dataflow JSON against docs/schemas/trill.v1.json.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="A .json file, or a directory to search recursively.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check docs/examples, docs/examples/dataflows, and .curio user projects.",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="Also check that every node type resolves to a template under packages/.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print nothing; communicate through the exit code alone.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=DEFAULT_MAX_ERRORS,
        metavar="N",
        help=f"Problems to print per file (default {DEFAULT_MAX_ERRORS}).",
    )
    args = parser.parse_args(argv)

    if not SCHEMA_PATH.is_file():
        print(f"Schema not found at {SCHEMA_PATH}", file=sys.stderr)
        return 2
    if args.all and args.paths:
        parser.error("pass either --all or explicit paths, not both")
    if not args.all and not args.paths:
        parser.error("pass one or more paths, or --all")

    validator = _load_schema()
    templates = _template_index() if args.resolve else None
    if args.resolve and not templates:
        print(f"No package manifests found under {REPO_ROOT / 'packages'}", file=sys.stderr)
        return 2

    if args.all:
        groups = _corpora()
    else:
        collected: list[Path] = []
        for raw in args.paths:
            target = Path(raw)
            if not target.exists():
                print(f"No such path: {raw}", file=sys.stderr)
                return 2
            collected += _files_under(target)
        groups = [("selected paths", collected)]

    status = 0
    checked = failed = 0
    for label, files in groups:
        if not args.quiet:
            if not files:
                print(f"\n{label}: none found")
                continue
            print(f"\n{label}: {len(files)} file(s)")
        for path in files:
            result = _validate_one(path, validator, templates, args.max_errors, args.quiet)
            status |= result
            checked += 1
            failed += result

    if not args.quiet:
        if checked == 0:
            print("\nNo trill files found to check.", file=sys.stderr)
            return 2
        print(f"\n{checked - failed}/{checked} file(s) validated against {_rel(SCHEMA_PATH)}")
        if failed:
            # Loud enough to notice, calm enough not to read as a build break:
            # .curio projects predate the schema and are expected to differ.
            print(
                f"{failed} file(s) did not validate. For projects under .curio/ this is "
                f"migration triage rather than a regression — see docs/TRILL-SPEC.md.",
                file=sys.stderr,
            )
    elif checked == 0:
        return 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())
