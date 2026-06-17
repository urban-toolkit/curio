import { Node as RFNode } from "reactflow";
import type { PackageTemplatePayload, PackagePayload } from "../api/packagesApi";
import { NodeDescriptor } from "../registry/types";
import { NodeTemplateId } from "../registry/types";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import { getFlowNodeCanonicalType } from "./flowNodeCanonicalType";
import {
  applyCanvasTemplateConfigToTemplateDraft,
  readCanvasTemplateConfig,
} from "./canvasTemplateConfig";
import {
  Draft,
  TemplateDraft,
  Category,
  Engine,
  makeDraft,
  factoryUiMakeId,
  STARTER_CODE,
  toApiPayload,
} from "../pages/nodes/factoryDraftModel";

/** Matches `PackageId` segment rules (`PACKAGE_DIR_RE` in `utk_curio.backend.app.packages.storage`). */
const PACK_ID_SEGMENT_MAX_LEN = 63;

/** Mirrors backend `KIND_ID_RE` (`utk_curio.backend.app.packages.storage`). */
const TEMPLATE_ID_SEGMENT_MAX_LEN = 63;

const WIZARD_CATEGORIES = new Set<string>(["data", "computation", "vis_grammar", "vis_simple", "flow"]);

export type StartersLookup = (type: NodeTemplateId, custom: boolean) => readonly { name: string; code: string }[];

/**
 * Normalizes arbitrary input into a single valid reverse‑DNS trailing segment (`[a-z][a-z0-9-]{0,62}`).
 * UUID hex without hyphens often starts with `0‑9`; those are prefixed so factory install validates.
 */
export function normalizePackageIdLeaf(raw: string): string {
  let s = String(raw ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "");
  s = s.replace(/-{2,}/g, "-").replace(/^-+/, "").replace(/-+$/, "");
  if (!s.length) {
    s = "palette";
  }
  if (!/^[a-z]/.test(s)) {
    s = `d${s}`;
  }
  if (s.length > PACK_ID_SEGMENT_MAX_LEN) {
    s = s.slice(0, PACK_ID_SEGMENT_MAX_LEN).replace(/-+$/, "");
  }
  if (!s.length || !/^[a-z]/.test(s)) {
    s = "draft";
  }
  return s;
}

export type FactoryInstallEnvelope = Record<string, unknown>;

/**
 * Payload for POST `/api/packages/factory/install`.
 * When `replace` is true the backend **replaces the installed package directory** (`packageId@major`)
 * so the **Packages palette** picks up the new manifest. It does **not** modify nodes on the canvas.
 */
export function buildFactoryInstallEnvelope(draft: Draft, replace?: boolean): FactoryInstallEnvelope {
  const payload = toApiPayload(draft);
  if (replace === undefined || !replace) return { ...payload };
  return { ...payload, replace: true };
}

export function runtimeCodeFromRfNode(node: RFNode<any>): string {
  const d = node?.data ?? {};
  if (typeof (d as { code?: unknown }).code === "string" && ((d as { code: string }).code as string).trim()) {
    return (d as { code: string }).code;
  }
  if (
    typeof (d as { defaultCode?: unknown }).defaultCode === "string" &&
    ((d as { defaultCode: string }).defaultCode as string).trim()
  ) {
    return (d as { defaultCode: string }).defaultCode as string;
  }
  return STARTER_CODE;
}

export function canonicalTemplateSlugForDescriptor(desc: NodeDescriptor): string {
  const id = String(desc.id);
  const m = id.match(/^[^/]+\/([^/@]+)@\d+$/);
  if (m) return m[1];
  return id.toLowerCase().replace(/_/g, "-");
}

function inferSourceFilename(packageRelativePath?: string): string {
  if (!packageRelativePath) return "default.py";
  const parts = packageRelativePath.split("/").filter(Boolean);
  const last = parts[parts.length - 1];
  return last || "default.py";
}

function deriveEngine(desc: NodeDescriptor): Engine {
  if (desc.editor === "grammar") return "javascript";
  return "python";
}

function ensurePorts(desc: NodeDescriptor): { inP: TemplateDraft["inputPorts"]; outP: TemplateDraft["outputPorts"] } {
  const inputPorts =
    desc.inputPorts.length === 0
      ? []
      : desc.inputPorts.map((p) => ({
          id: factoryUiMakeId(),
          types: p.types.join(","),
          cardinality: String(p.cardinality ?? "1"),
        }));
  const outputPortsRaw =
    desc.outputPorts.length === 0
      ? [{ id: factoryUiMakeId(), types: "JSON", cardinality: "1" }]
      : desc.outputPorts.map((p) => ({
          id: factoryUiMakeId(),
          types: p.types.join(","),
          cardinality: String(p.cardinality ?? "1"),
        }));
  return { inP: inputPorts, outP: outputPortsRaw };
}

/** Maps manifest default template paths to dropdown names (see `packageNodeBehavior.tsx`). */
function sourceDisplayName(sourcePath: string | undefined): string | undefined {
  if (!sourcePath) return undefined;
  const basename = sourcePath.split("/").pop() ?? "";
  if (!basename) return undefined;
  const stem = basename.replace(/\.[^.]+$/u, "");
  return stem.replace(/_/g, " ");
}

/** Unique slug within `occupied` (`[a-z][a-z0-9-]…`). */
function forkTemplateSlugAwayFrom(baseSlug: string, occupied: ReadonlyMap<string, unknown>): string {
  for (let n = 0; n < 64; n++) {
    const leaf = normalizePackageIdLeaf(`${factoryUiMakeId()}${n}${baseSlug}`);
    let cand = `${baseSlug}-k-${leaf}`;
    if (cand.length > TEMPLATE_ID_SEGMENT_MAX_LEN) {
      cand = cand.slice(0, TEMPLATE_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "");
    }
    if (cand && /^[a-z][a-z0-9-]*$/u.test(cand) && !occupied.has(cand)) return cand;
  }
  const fallback = `${baseSlug}-k-${normalizePackageIdLeaf(factoryUiMakeId())}`;
  return fallback.length > TEMPLATE_ID_SEGMENT_MAX_LEN
    ? fallback.slice(0, TEMPLATE_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "")
    : fallback;
}

export function descriptorToTemplateDraft(
  desc: NodeDescriptor,
  code: string,
  kindIdOverride?: string,
  labelOverride?: string,
): TemplateDraft {
  const templateId = kindIdOverride ?? canonicalTemplateSlugForDescriptor(desc);
  const sourceFilename = inferSourceFilename(desc.package?.source);

  const { inP, outP } = ensurePorts(desc);

  return {
    id: templateId,
    label: labelOverride?.trim() || desc.label || templateId,
    category: desc.category as Category,
    engine: deriveEngine(desc),
    editor: desc.editor,
    description: desc.description ?? "",
    hasCode: !!desc.hasCode,
    hasWidgets: !!desc.hasWidgets,
    hasGrammar: !!desc.hasGrammar,
    inputPorts: inP,
    outputPorts: outP,
    sourceFilename,
    sourceCode: code?.trim()?.length ? code : STARTER_CODE,
  };
}

export function normalizeTemplateLabel(label: string): string {
  return label.trim().toLowerCase();
}

/** Canvas-local template title; falls back to registry descriptor label. */
export function canvasTemplateLabelFromNode(node: { data: object }, desc: NodeDescriptor): string {
  const raw = (node.data as { packageTemplateLabel?: unknown })?.packageTemplateLabel;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return desc.label || canonicalTemplateSlugForDescriptor(desc);
}

function templateDraftFromCanvasNode(
  node: RFNode<any>,
  desc: NodeDescriptor,
  body: string,
  kindIdOverride?: string,
): TemplateDraft {
  const label = canvasTemplateLabelFromNode(node, desc);
  const base = descriptorToTemplateDraft(desc, body, kindIdOverride, label);
  const config = readCanvasTemplateConfig(node);
  return applyCanvasTemplateConfigToTemplateDraft(base, config, label);
}

function categoryFromPackageTemplate(cat: string): Category {
  return WIZARD_CATEGORIES.has(cat) ? (cat as Category) : "computation";
}

function depsRows(record: Record<string, string>): { id: string; pkg: string; range: string }[] {
  return Object.entries(record).map(([pkg, range]) => ({
    id: factoryUiMakeId(),
    pkg,
    range: range ?? "*",
  }));
}

function seedCodeForPackageTemplatePayload(template: PackageTemplatePayload, getStarters?: StartersLookup): string {
  if (!getStarters) return STARTER_CODE;
  const starters = [...getStarters(template.id as NodeTemplateId, false)];
  const wanted = sourceDisplayName(template.source ?? undefined);
  const hit = wanted ? starters.find((t) => t.name === wanted) : starters[0];
  const body = typeof hit?.code === "string" ? hit.code : "";
  return body.trim().length ? body : STARTER_CODE;
}

function packageTemplatePayloadToTemplateDraft(template: PackageTemplatePayload, getStarters?: StartersLookup): TemplateDraft {
  const sourceFilename =
    template.source?.split("/").pop()?.trim() || `${template.templateId}.py`;
  const inputPorts =
    template.inputPorts?.map((p) => ({
      id: factoryUiMakeId(),
      types: (p.types ?? []).join(","),
      cardinality: String(p.cardinality ?? "1"),
    })) ?? [];
  const outputPortsRaw =
    template.outputPorts?.length ?
      template.outputPorts.map((p) => ({
        id: factoryUiMakeId(),
        types: (p.types ?? []).join(","),
        cardinality: String(p.cardinality ?? "1"),
      }))
    : [{ id: factoryUiMakeId(), types: "JSON", cardinality: "1" }];
  const engine: Engine = template.engine === "javascript" ? "javascript" : "python";
  return {
    id: template.templateId,
    label: template.label || template.templateId,
    category: categoryFromPackageTemplate(template.category),
    engine,
    editor: template.editor,
    description: template.description ?? "",
    hasCode: !!template.hasCode,
    hasWidgets: !!template.hasWidgets,
    hasGrammar: !!template.hasGrammar,
    inputPorts,
    outputPorts: outputPortsRaw,
    behavior: template.behavior ?? undefined,
    iconRef: template.iconRef ?? undefined,
    paletteOrder: typeof template.paletteOrder === "number" ? template.paletteOrder : undefined,
    sourceFilename,
    sourceCode: seedCodeForPackageTemplatePayload(template, getStarters),
  };
}

/** Factory draft from ``GET /api/packages`` row — used for palette “publish to catalog”. */
export function draftFromInstalledPackagePayload(
  pkg: PackagePayload,
  getStarters?: StartersLookup,
): Draft {
  const d = makeDraft();
  d.packageId = pkg.packageId;
  d.major = pkg.major;
  d.version = pkg.version;
  d.name = pkg.name;
  d.publisher = pkg.publisher;
  d.description = pkg.description;
  d.license = pkg.license ?? "MIT";
  d.permissions = [...pkg.permissions];
  d.pythonDeps = depsRows(pkg.dependencies.python ?? {});
  d.jsDeps = depsRows(pkg.dependencies.js ?? {});
  d.packageDeps = depsRows(pkg.dependencies.packages ?? {});
  d.lineage = pkg.lineage
    ? {
        forkedFrom: {
          packageId: pkg.lineage.forkedFrom.packageId,
          major: pkg.lineage.forkedFrom.major,
        },
        root: {
          packageId: pkg.lineage.root.packageId,
          major: pkg.lineage.root.major,
        },
      }
    : null;
  d.templates = pkg.templates.map((k) => packageTemplatePayloadToTemplateDraft(k, getStarters));
  if (typeof pkg.createdAt === "string" && pkg.createdAt.trim()) {
    d.createdAt = pkg.createdAt.trim();
  }
  return d;
}

export const SAVE_AS_NEW_PACK = "__save_as_new__";

/** True when Save As into `package` would overwrite an existing kind with the same label. */
export function saveAsWouldReplaceByLabel(pkg: PackagePayload, nodeLabel: string): boolean {
  const norm = normalizeTemplateLabel(nodeLabel);
  if (!norm) return false;
  return pkg.templates.some((k) => normalizeTemplateLabel(k.label) === norm);
}

/** Build a factory install draft when saving a single canvas node into a package (Save As). */
export function buildSaveAsInstallDraft(opts: {
  canvasNode: RFNode<any>;
  target:
    | { kind: "new"; packageDisplayName?: string }
    | { kind: "installed"; package: PackagePayload };
  getStarters?: StartersLookup;
}): Draft | null {
  const nt = getFlowNodeCanonicalType(opts.canvasNode as RFNode);
  if (!nt) return null;
  const desc = tryGetNodeDescriptor(nt as NodeTemplateId);
  if (!desc) return null;

  const label = canvasTemplateLabelFromNode(opts.canvasNode, desc);
  const body = runtimeCodeFromRfNode(opts.canvasNode);
  const slugBase = canonicalTemplateSlugForDescriptor(desc);

  if (opts.target.kind === "new") {
    const leaf = normalizePackageIdLeaf(factoryUiMakeId());
    const draft = makeDraft();
    draft.packageId = `curio.canvas.draft.${leaf}`;
    draft.name = opts.target.packageDisplayName?.trim() || `${label} package`;
    draft.publisher = "Local palette";
    draft.description = "Created from canvas Save As.";
    draft.templates = [templateDraftFromCanvasNode(opts.canvasNode, desc, body, slugBase)];
    return draft;
  }

  const draft = draftFromInstalledPackagePayload(opts.target.package, opts.getStarters);

  const labelMatchIdx = draft.templates.findIndex(
    (k) => normalizeTemplateLabel(k.label) === normalizeTemplateLabel(label),
  );
  if (labelMatchIdx >= 0) {
    const existingId = draft.templates[labelMatchIdx]!.id;
    draft.templates[labelMatchIdx] = templateDraftFromCanvasNode(opts.canvasNode, desc, body, existingId);
    return draft;
  }

  const kindsMap = new Map(draft.templates.map((k) => [k.id, k]));
  const templateId = kindsMap.has(slugBase) ? forkTemplateSlugAwayFrom(slugBase, kindsMap) : slugBase;
  draft.templates.push(templateDraftFromCanvasNode(opts.canvasNode, desc, body, templateId));
  return draft;
}
