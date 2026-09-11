#!/usr/bin/env python3
"""Scaffold a new Curio node package.

WHY
---
A node package is a directory with a ``manifest.json`` declaring one or more
node templates. Written by hand it is easy to get subtly wrong — the id
patterns, the required template fields, the port shapes, and the
``integrity.json`` companion all have to line up before the palette will show
your node. This script emits a package that is valid on the first run, so the
first thing you debug is your own node logic rather than the envelope.

Two flavours, matching the two ways a node can be implemented:

* **default** — a Python node. The template uses the built-in ``code``
  behavior, so Curio renders its standard code editor and runs your Python in
  the sandbox. No frontend build, no JavaScript.
* ``--with-ui`` — a node with its own React interface. Adds a behavior hook
  plus the bundle entry point and declares ``behaviorScript`` in the manifest.
  This flavour needs one extra step: a row in
  ``utk_curio/frontend/urban-workflows/webpack.packages.config.js`` and a
  ``npm run build:packages``. The script prints the exact row to paste.

See ``docs/AUTHORING-NODES.md`` for the full walkthrough.

HOW
---
    python scripts/new_package.py me.roughness
    python scripts/new_package.py me.heatmap --with-ui
    python scripts/new_package.py me.thing --major 2 --template-id my-thing

The package lands in ``packages/<id>@<major>/``. Add it from the canvas via
**Node Catalog → Browse Node Catalog + → Browse → Add to dataflow**, then use
**Reload** on the **In dataflow** tab to pick up later edits.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.packages.installer import (  # noqa: E402
    refresh_packageage_integrity,
)
from utk_curio.backend.app.packages.manifest import (  # noqa: E402
    ManifestError,
    load_packageage_manifest,
)

# Mirrors the schema's `id` pattern (docs/schemas/node-package.v4.json).
PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*[a-z0-9]$")
# Mirrors storage.TEMPLATE_ID_RE.
TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

SCHEMA_URL = (
    "https://raw.githubusercontent.com/urban-toolkit/curio/main/"
    "docs/schemas/node-package.v4.json"
)


# ── Generated file bodies ──────────────────────────────────────────────────
#
# Plain (non-f) strings with __TOKEN__ placeholders. The generated files are
# full of JS/JSX braces, so f-string interpolation here would mean doubling
# every one of them — token replacement keeps these templates readable and
# copy-pasteable into a real .tsx file.

_PYTHON_TEMPLATE = r'''"""__LABEL__ — Python node.

``arg`` holds whatever the upstream port produced. With one upstream node wired
it is that node's output directly; with several (typically through a Merge
Flow) it is a list in edge order.

Whatever you ``return`` becomes this node's output, and the port types declared
in manifest.json tell Curio how to carry it downstream.
"""

import pandas as pd

df = arg if isinstance(arg, pd.DataFrame) else pd.DataFrame(arg)

# Replace this with your own transformation.
df = df.copy()
df["row_number"] = range(1, len(df) + 1)

return df
'''

_BEHAVIOR_TEMPLATE = r"""import React, { useCallback, useEffect, useState } from 'react';
import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * __LABEL__ — a node with its own React interface.
 *
 * A behavior hook is a React custom hook. It receives the node's runtime
 * `data` and the shared `nodeState`, and returns the pieces of the node it
 * wants to override — here just `contentComponent`, the JSX rendered inside
 * the node body. All the normal rules of hooks apply.
 */

// Read the host's backend URL at runtime. Do NOT use `process.env.BACKEND_URL`
// here — that bakes your build machine's URL into the bundle you ship.
const BACKEND_URL: string =
  (typeof window !== 'undefined' && (window as any).curio?.backendUrl) || '';

/** The session token lives in a cookie; the artifact endpoint requires it. */
function sessionToken(): string {
  if (typeof document === 'undefined') return '';
  const hit = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : '';
}

// Payload shapes Curio recognises directly. Anything else is a generic
// envelope wrapped around one of these, so peel until we reach a known type.
const KNOWN_TYPES = new Set(['dataframe', 'geodataframe', 'outputs']);

function unwrap(value: any): any {
  let current = value;
  while (
    current && typeof current === 'object' &&
    typeof current.dataType === 'string' &&
    !KNOWN_TYPES.has(current.dataType) &&
    'data' in current
  ) {
    current = current.data;
  }
  return current;
}

/**
 * Turn whatever landed on `data.input` into real data.
 *
 * Upstream hands you one of two shapes, and a custom-UI node has to cope with
 * both:
 *
 *   { path: 'art-12', dataType: 'dataframe' }  a sandbox artifact reference,
 *                                              which is what every Python or
 *                                              JS node produces -> fetch it
 *   { data: {...},    dataType: 'dataframe' }  an inline payload, which is what
 *                                              another custom-UI node produces
 *                                              -> use it as-is
 */
async function resolveInput(input: any): Promise<any> {
  if (input == null || input === '') return null;
  const ref = typeof input === 'string' ? input : input.path ?? input.dataset;
  if (typeof ref === 'string' && ref.trim()) {
    const token = sessionToken();
    const res = await fetch(
      `${BACKEND_URL}/get?fileName=${encodeURIComponent(ref.trim())}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!res.ok) throw new Error(`Could not read upstream data (HTTP ${res.status})`);
    return unwrap(await res.json());
  }
  return unwrap(input);
}

/** A `dataframe` payload is column-oriented. Curio serialises with
 *  `to_dict(orient='list')`, so each column is an ARRAY; a hand-written
 *  spec may instead use a row map keyed by index. Accept both - a node
 *  that requires the row map sees no data at all from Curio (#194). */
function columnNames(payload: any): string[] {
  const frame = payload?.dataType === 'dataframe' ? payload.data : payload;
  if (!frame || typeof frame !== 'object') return [];
  return Object.keys(frame);
}

export const __HOOK_NAME__: NodeBehaviorHook = (data, nodeState) => {
  const [payload, setPayload] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [column, setColumn] = useState<string>('');

  // Re-resolve whenever upstream produces something new.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    resolveInput(data.input)
      .then((resolved) => {
        if (cancelled) return;
        setPayload(resolved);
        const cols = columnNames(resolved);
        setColumn((prev) => (prev && cols.includes(prev) ? prev : cols[0] ?? ''));
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [data.input]);

  const columns = columnNames(payload);

  // Push a result downstream. `dataType` must match an output port type
  // declared in manifest.json, lowercased.
  const emit = useCallback(() => {
    const frame = payload?.dataType === 'dataframe' ? payload.data : payload;
    if (!frame || !column) return;
    try {
      data.outputCallback(data.nodeId, {
        data: { [column]: frame[column] },
        dataType: 'dataframe',
      });
      nodeState.setOutput({ code: 'success', content: '' });
    } catch (e: any) {
      nodeState.setOutput({ code: 'error', content: e.message || String(e) });
    }
  }, [payload, column, data, nodeState]);

  const contentComponent = (
    <div
      style={{
        padding: 12,
        fontSize: 13,
        fontFamily: 'sans-serif',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <strong>__LABEL__</strong>
      {error ? (
        <span style={{ color: '#c0392b' }}>{error}</span>
      ) : columns.length === 0 ? (
        <span style={{ color: '#888' }}>Connect a DataFrame upstream and run it.</span>
      ) : (
        <>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ color: '#666', fontSize: 11 }}>Column</span>
            <select value={column} onChange={(e) => setColumn(e.target.value)}>
              {columns.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={emit} disabled={!column}>
            Send this column downstream
          </button>
        </>
      )}
    </div>
  );

  return { contentComponent };
};
"""

_INDEX_TEMPLATE = r"""/**
 * Bundle entry point for this package.
 *
 * Webpack compiles this file into `../scripts/behaviors.js`. At boot Curio
 * fetches that bundle for every installed package whose manifest declares
 * `behaviorScript` and evaluates it, so the side effect below is what actually
 * registers the hook. The key passed to `registerBehavior` must match the
 * template's `behavior` field in manifest.json.
 *
 * React, ReactDOM and ReactFlow are externalised to `window` so this bundle
 * shares Curio's own instances — two copies of React break every hook.
 */

import { __HOOK_NAME__ } from './__HOOK_FILE__';

type CurioGlobal = {
  registerBehavior: (key: string, hook: any) => void;
};

function registerAll(curio: CurioGlobal) {
  curio.registerBehavior('__TEMPLATE_ID__', __HOOK_NAME__);
}

if (typeof window !== 'undefined') {
  const w = window as any;
  if (w.curio && typeof w.curio.registerBehavior === 'function') {
    registerAll(w.curio);
  } else {
    // This bundle can load before Curio publishes its registry. Queue the
    // registration; the boot sequence drains the list once `window.curio` lands.
    const pending: Array<(c: CurioGlobal) => void> = (w.__curioPendingPackages__ ??= []);
    pending.push(registerAll);
  }
}
"""

LICENSE_TEXT = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


# ── Naming helpers ─────────────────────────────────────────────────────────


def _default_template_id(package_id: str) -> str:
    """``me.my-thing`` -> ``my-thing``; underscores and dots become dashes."""
    tail = package_id.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9-]", "-", tail).strip("-") or "my-node"


def _label_from(template_id: str) -> str:
    return " ".join(part.capitalize() for part in template_id.split("-"))


def _camel_from(template_id: str) -> str:
    parts = [p for p in template_id.split("-") if p]
    if not parts:
        return "myNode"
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ── Body builders ──────────────────────────────────────────────────────────


def _python_source(label: str) -> str:
    return _PYTHON_TEMPLATE.replace("__LABEL__", label)


def _behavior_source(*, label: str, hook_name: str) -> str:
    return _BEHAVIOR_TEMPLATE.replace("__LABEL__", label).replace(
        "__HOOK_NAME__", hook_name
    )


def _index_source(*, template_id: str, hook_name: str, hook_file: str) -> str:
    return (
        _INDEX_TEMPLATE.replace("__HOOK_NAME__", hook_name)
        .replace("__HOOK_FILE__", hook_file)
        .replace("__TEMPLATE_ID__", template_id)
    )


def _manifest(
    *,
    package_id: str,
    major: int,
    template_id: str,
    label: str,
    with_ui: bool,
) -> dict:
    template: dict = {
        "id": template_id,
        "label": label,
        "description": (
            f"{label}: describe what this node does. The palette shows this text."
        ),
        "category": "computation",
        "engine": "python",
        "editor": "none" if with_ui else "code",
        # A custom-UI node registers its own behavior key (matched in
        # sources/index.tsx); a Python node reuses Curio's built-in "code".
        "behavior": template_id if with_ui else "code",
        "iconRef": "fa-solid:cube",
        "hasCode": not with_ui,
        "hasWidgets": False,
        "hasGrammar": False,
        "inputPorts": [{"cardinality": "1", "types": ["DATAFRAME"]}],
        "outputPorts": [{"cardinality": "1", "types": ["DATAFRAME"]}],
    }
    if not with_ui:
        template["source"] = f"sources/{template_id}.py"

    manifest: dict = {
        "$schema": SCHEMA_URL,
        "id": package_id,
        "name": label,
        "publisher": "Your name",
        "description": f"{label}: a Curio node package.",
        "version": "1.0.0",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Declared imports in your source are detected automatically when a
        # package is built through the UI; fill these in by hand otherwise.
        "dependencies": {"js": {}, "packages": {}, "python": {}},
        "permissions": [],
        "templates": [template],
    }
    if with_ui:
        manifest["behaviorScript"] = "scripts/behaviors.js"
    return manifest


def _readme(*, label: str, package_id: str, major: int, with_ui: bool) -> str:
    kind = "a custom React interface" if with_ui else "Python running in the sandbox"
    build = (
        "\n## Building\n\n"
        "This package ships a compiled behavior bundle. After editing anything "
        "under `sources/`:\n\n"
        "```bash\n"
        "cd utk_curio/frontend/urban-workflows\n"
        "npm run build:packages\n"
        "```\n\n"
        "Then click **Reload** on this package in the catalog drawer's "
        "**In dataflow** tab.\n"
        if with_ui
        else ""
    )
    return f"""# {label}

`{package_id}@{major}`

One node, implemented with {kind}.

This README is shown in the Node Catalog when someone browses your package.
Cover what the node does, what it expects on its input port, what it emits, and
anything a user has to set up first (API keys, large downloads, costs).

## Nodes

| Node | Input | Output | What it does |
|---|---|---|---|
| {label} | DataFrame | DataFrame | _describe it here_ |
{build}
## License

MIT
"""


# ── Main ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new Curio node package under packages/.",
    )
    parser.add_argument(
        "package_id",
        metavar="PACKAGE_ID",
        help="Reverse-domain id, e.g. 'me.roughness' or 'edu.uic.cs529.alice'",
    )
    parser.add_argument(
        "--major", type=int, default=1, help="Major version (default: 1)"
    )
    parser.add_argument(
        "--template-id",
        default=None,
        help="Kebab-case node id (default: derived from the package id)",
    )
    parser.add_argument(
        "--label", default=None, help="Display name shown in the palette"
    )
    parser.add_argument(
        "--with-ui",
        action="store_true",
        help="Scaffold a custom React interface instead of a code-editor node",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Directory to create the package in (default: <repo>/packages)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing package directory"
    )
    args = parser.parse_args(argv)

    package_id: str = args.package_id.strip().lower()
    if not PACKAGE_ID_RE.match(package_id):
        print(
            f"error: package id {package_id!r} is invalid.\n"
            "       Use lowercase letters, digits, '.', '-' and '_'; start with a\n"
            "       letter and end with a letter or digit. Example: me.roughness",
            file=sys.stderr,
        )
        return 2
    if args.major < 0:
        print("error: --major must be >= 0", file=sys.stderr)
        return 2

    template_id: str = (
        args.template_id or _default_template_id(package_id)
    ).strip().lower()
    if not TEMPLATE_ID_RE.match(template_id):
        print(
            f"error: template id {template_id!r} is invalid.\n"
            "       Use kebab-case: a lowercase letter, then letters, digits or '-'.",
            file=sys.stderr,
        )
        return 2

    label: str = args.label or _label_from(template_id)
    dir_name = f"{package_id}@{args.major}"
    dest_root = Path(args.dest).resolve() if args.dest else REPO_ROOT / "packages"
    package_root = dest_root / dir_name

    if package_root.exists() and not args.force:
        print(
            f"error: {package_root} already exists. Pass --force to overwrite it.",
            file=sys.stderr,
        )
        return 1

    # ── Write ──
    (package_root / "sources").mkdir(parents=True, exist_ok=True)

    manifest = _manifest(
        package_id=package_id,
        major=args.major,
        template_id=template_id,
        label=label,
        with_ui=args.with_ui,
    )
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (package_root / "README.md").write_text(
        _readme(
            label=label, package_id=package_id, major=args.major, with_ui=args.with_ui
        ),
        encoding="utf-8",
    )
    (package_root / "LICENSE").write_text(
        LICENSE_TEXT.format(year=datetime.now(timezone.utc).year, holder="Your name"),
        encoding="utf-8",
    )

    written = ["manifest.json", "README.md", "LICENSE"]

    if args.with_ui:
        camel = _camel_from(template_id)
        hook_name = f"use{camel[0].upper()}{camel[1:]}Behavior"
        hook_file = f"{camel}Behavior"
        (package_root / "sources" / f"{hook_file}.tsx").write_text(
            _behavior_source(label=label, hook_name=hook_name), encoding="utf-8"
        )
        (package_root / "sources" / "index.tsx").write_text(
            _index_source(
                template_id=template_id, hook_name=hook_name, hook_file=hook_file
            ),
            encoding="utf-8",
        )
        written += [f"sources/{hook_file}.tsx", "sources/index.tsx"]
    else:
        (package_root / "sources" / f"{template_id}.py").write_text(
            _python_source(label), encoding="utf-8"
        )
        written.append(f"sources/{template_id}.py")

    # ── Validate + hash ──
    try:
        load_packageage_manifest(package_root)
    except ManifestError as exc:
        print(f"error: the generated manifest did not validate: {exc}", file=sys.stderr)
        return 1
    refresh_packageage_integrity(package_root)
    written.append("integrity.json")

    # ── Report ──
    try:
        rel: Path | str = package_root.relative_to(REPO_ROOT)
    except ValueError:
        rel = package_root
    print(f"Created {rel}")
    for name in written:
        print(f"  {name}")
    print()
    print("Next steps:")
    step = 1
    if args.with_ui:
        print(
            f"  {step}. Add this entry to PACKAGE_ENTRIES in"
            " utk_curio/frontend/urban-workflows/webpack.packages.config.js:\n"
        )
        print(f'       {{\n         id: "{dir_name}",')
        print(
            "         entry: path.resolve(__dirname,"
            f' "../../../packages/{dir_name}/sources/index.tsx"),'
        )
        print(
            "         outputDir: path.resolve(__dirname,"
            f' "../../../packages/{dir_name}/scripts"),'
        )
        print("       },\n")
        step += 1
        print(f"  {step}. Build the bundle:")
        print(
            "       cd utk_curio/frontend/urban-workflows"
            " && npm run build:packages\n"
        )
        step += 1
    print(
        f"  {step}. Start Curio, open a dataflow, then Node Catalog ->"
        " Browse Node Catalog + -> Browse -> Add to dataflow."
    )
    step += 1
    print(
        f"  {step}. After every later edit: re-run the build (if any), then click"
        " Reload on the package in the drawer's In dataflow tab."
    )
    print()
    print("Docs: docs/AUTHORING-NODES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
