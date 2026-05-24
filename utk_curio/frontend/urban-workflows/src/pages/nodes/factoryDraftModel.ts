

/**
 * Shared wizard draft shapes + serialization shared by `NodeFactory` and
 * the canvas palette Save / Factory hydrate flow.
 */

export type Category = "data" | "computation" | "vis_grammar" | "vis_simple" | "flow";
export type Engine = "python" | "javascript";
/** Wizard / manifest editor mode (maps to manifest `editor`). */
export type Editor = "code" | "widgets" | "grammar" | "none";

export interface PortDraft {
  id: string;
  types: string;
  cardinality: string;
}

/** Mirrors manifest ``lineage`` (backend ``PackageLineage``). */
export interface PackageLineageCoordDraft {
  packageId: string;
  major: number;
}

export interface PackageLineageDraft {
  forkedFrom: PackageLineageCoordDraft;
  root: PackageLineageCoordDraft;
}

export interface KindDraft {
  id: string;
  label: string;
  category: Category;
  engine: Engine;
  editor: Editor;
  description: string;
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  inputPorts: PortDraft[];
  outputPorts: PortDraft[];
  /** Manifest fields surfaced from `curio.builtin@1` lifecycle/icon registries. Optional for new kinds. */
  lifecycle?: string;
  iconRef?: string;
  paletteOrder?: number;
  /** Package-relative source filename, e.g. "uhvi-load.py" or "chart.vl.json". Empty when the kind ships no starter. */
  sourceFilename: string;
  /** Full source body, written to `sources/<sourceFilename>` on build. */
  sourceCode: string;
}

export interface Draft {
  packageId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string;
  curioRuntime: string;
  permissions: string[];
  pythonDeps: { id: string; pkg: string; range: string }[];
  jsDeps: { id: string; pkg: string; range: string }[];
  packageDeps: { id: string; pkg: string; range: string }[];
  kinds: KindDraft[];
  /** Fork provenance when saving from the palette editor against an installed package. */
  lineage: PackageLineageDraft | null;
  /** Manifest ``createdAt`` (ISO instant). Omit to let backend stamp UTC on build/install. */
  createdAt?: string;
  readme: string;
  licenseText: string;
}



export const STARTER_CODE =
  "# Package source — runs in the shared sandbox interpreter.\n" +
  "# Replace this body with your implementation.\n\n" +
  "def run(input):\n" +
  '    return {"hello": "from the node factory"}\n';

export function factoryUiMakeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function makeKind(kindId: string = "demo-kind"): KindDraft {
  return {
    id: kindId,
    label: "New kind",
    category: "computation",
    engine: "python",
    editor: "code",
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    inputPorts: [],
    outputPorts: [{ id: factoryUiMakeId(), types: "JSON", cardinality: "1" }],
    lifecycle: "code",
    sourceFilename: `${kindId}.py`,
    sourceCode: STARTER_CODE,
  };
}

export function makeDraft(): Draft {
  return {
    packageId: "",
    major: 1,
    version: "0.1.0",
    name: "",
    publisher: "",
    description: "",
    license: "MIT",
    curioRuntime: ">=0.5.0",
    permissions: [],
    pythonDeps: [],
    jsDeps: [],
    packageDeps: [],
    kinds: [makeKind()],
    lineage: null,
    readme: "",
    licenseText: "",
  };
}

function splitTypes(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function depsToMap(entries: { pkg: string; range: string }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of entries) {
    if (!e.pkg.trim()) continue;
    out[e.pkg.trim()] = e.range.trim() || "*";
  }
  return out;
}

export function toApiPayload(d: Draft): {
  manifest: Record<string, unknown>;
  sources: Record<string, { filename: string; code: string }>;
  readme: string;
  license_text: string;
} {
  const manifest: Record<string, unknown> = {
    id: d.packageId,
    version: d.version,
    name: d.name,
    publisher: d.publisher,
    description: d.description,
    license: d.license || null,
    compatibility: {
      curioRuntime: d.curioRuntime,
      major: d.major,
    },
    permissions: d.permissions,
    dependencies: {
      packages: depsToMap(d.packageDeps),
      python: depsToMap(d.pythonDeps),
      js: depsToMap(d.jsDeps),
    },
    kinds: d.kinds.map((k) => {
      const entry: Record<string, unknown> = {
        id: k.id,
        label: k.label,
        category: k.category,
        engine: k.engine,
        editor: k.editor,
        description: k.description,
        hasCode: k.hasCode,
        hasWidgets: k.hasWidgets,
        hasGrammar: k.hasGrammar,
        inputPorts: k.inputPorts.map((p) => ({
          types: splitTypes(p.types),
          cardinality: p.cardinality,
        })),
        outputPorts: k.outputPorts.map((p) => ({
          types: splitTypes(p.types),
          cardinality: p.cardinality,
        })),
      };
      if (k.lifecycle) entry.lifecycle = k.lifecycle;
      if (k.iconRef) entry.iconRef = k.iconRef;
      if (typeof k.paletteOrder === "number") entry.paletteOrder = k.paletteOrder;
      if (k.sourceFilename) entry.source = `sources/${k.sourceFilename}`;
      return entry;
    }),
  };

  if (typeof d.createdAt === "string" && d.createdAt.trim()) {
    manifest.createdAt = d.createdAt.trim();
  }

  if (d.lineage) {
    manifest.lineage = {
      forkedFrom: {
        packageId: d.lineage.forkedFrom.packageId,
        major: d.lineage.forkedFrom.major,
      },
      root: {
        packageId: d.lineage.root.packageId,
        major: d.lineage.root.major,
      },
    };
  }

  const sources: Record<string, { filename: string; code: string }> = {};
  for (const k of d.kinds) {
    if (k.sourceFilename) {
      sources[k.id] = { filename: k.sourceFilename, code: k.sourceCode };
    }
  }
  return {
    manifest,
    sources,
    readme: d.readme,
    license_text: d.licenseText,
  };
}
