

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

/** Mirrors manifest ``lineage`` (backend ``PackLineage``). */
export interface PackLineageCoordDraft {
  packId: string;
  major: number;
}

export interface PackLineageDraft {
  forkedFrom: PackLineageCoordDraft;
  root: PackLineageCoordDraft;
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
  templateDir: string;
  defaultTemplate: string;
  defaultTemplateName: string;
  defaultTemplateCode: string;
}

export interface Draft {
  packId: string;
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
  packDeps: { id: string; pkg: string; range: string }[];
  kinds: KindDraft[];
  /** Fork provenance when saving from the palette editor against an installed pack. */
  lineage: PackLineageDraft | null;
  /** Manifest ``createdAt`` (ISO instant). Omit to let backend stamp UTC on build/install. */
  createdAt?: string;
  readme: string;
  licenseText: string;
}



export const STARTER_CODE =
  "# Pack template — runs in the shared sandbox interpreter.\n" +
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
    templateDir: `templates/${kindId}`,
    defaultTemplate: `templates/${kindId}/Default.py`,
    defaultTemplateName: "Default.py",
    defaultTemplateCode: STARTER_CODE,
  };
}

export function makeDraft(): Draft {
  return {
    packId: "",
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
    packDeps: [],
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
  sources: Record<string, Record<string, string>>;
  readme: string;
  license_text: string;
} {
  const manifest: Record<string, unknown> = {
    id: d.packId,
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
      packs: depsToMap(d.packDeps),
      python: depsToMap(d.pythonDeps),
      js: depsToMap(d.jsDeps),
    },
    kinds: d.kinds.map((k) => ({
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
      templateDir: k.templateDir,
      defaultTemplate: k.defaultTemplate,
    })),
  };

  if (typeof d.createdAt === "string" && d.createdAt.trim()) {
    manifest.createdAt = d.createdAt.trim();
  }

  if (d.lineage) {
    manifest.lineage = {
      forkedFrom: {
        packId: d.lineage.forkedFrom.packId,
        major: d.lineage.forkedFrom.major,
      },
      root: {
        packId: d.lineage.root.packId,
        major: d.lineage.root.major,
      },
    };
  }

  const sources: Record<string, Record<string, string>> = {};
  for (const k of d.kinds) {
    sources[k.id] = { [k.defaultTemplateName]: k.defaultTemplateCode };
  }
  return {
    manifest,
    sources,
    readme: d.readme,
    license_text: d.licenseText,
  };
}
