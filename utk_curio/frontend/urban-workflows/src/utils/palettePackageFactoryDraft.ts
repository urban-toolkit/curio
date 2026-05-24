import { Node as RFNode } from "reactflow";
import type { NavigateFunction } from "react-router-dom";
import type { PackageKindPayload, PackagePayload } from "../api/packagesApi";
import { NodeDescriptor } from "../registry/types";
import { NodeKindId } from "../registry/types";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import { getFlowNodeCanonicalType } from "./flowNodeCanonicalType";
import {
  applyCanvasKindConfigToKindDraft,
  readCanvasKindConfig,
} from "./canvasKindConfig";
import type { PackageStagedRow } from "../providers/PackagePaletteContext";
import {
  Draft,
  KindDraft,
  Category,
  Engine,
  makeDraft,
  factoryUiMakeId,
  STARTER_CODE,
  toApiPayload,
  type PackageLineageDraft,
} from "../pages/nodes/factoryDraftModel";

export const FACTORY_HYDRATE_SESSION_KEY = "curio.factoryWizardHydrateDraft.v1";

/** Matches `PackageId` segment rules (`PACKAGE_DIR_RE` in `utk_curio.backend.app.packages.storage`). */
const PACK_ID_SEGMENT_MAX_LEN = 63;

/** Mirrors backend `KIND_ID_RE` (`utk_curio.backend.app.packages.storage`). */
const KIND_ID_SEGMENT_MAX_LEN = 63;

const WIZARD_CATEGORIES = new Set<string>(["data", "computation", "vis_grammar", "vis_simple", "flow"]);

export type TemplatesLookup = (type: NodeKindId, custom: boolean) => readonly { name: string; code: string }[];

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

export type PalettePackageGroupLite = {
  key: string;
  label: string;
  descriptors: NodeDescriptor[];
};

/**
 * Parse a palette section key ``<packageId>@<major>`` (used for installed packages).
 * Returns null for draft sections (``__draft__:…``) or malformed keys.
 */
export function parsePalettePackageSectionKey(key: string): { packageId: string; major: number } | null {
  const at = key.lastIndexOf("@");
  if (at <= 0) return null;
  const packageId = key.slice(0, at).trim();
  const majorRaw = key.slice(at + 1).trim();
  if (!packageId || !majorRaw) return null;
  const major = Number(majorRaw);
  if (!Number.isInteger(major) || major < 0) return null;
  return { packageId, major };
}

function lineageDraftForInstalledPackageGroup(group: PalettePackageGroupLite): PackageLineageDraft | null {
  const forkedFrom = parsePalettePackageSectionKey(group.key);
  if (!forkedFrom) return null;
  const anchor = group.descriptors[0]?.package?.lineage?.root;
  const root = anchor ? { packageId: anchor.packageId, major: anchor.major } : forkedFrom;
  return { forkedFrom, root };
}

export type FactoryInstallEnvelope = Record<string, unknown>;

export function storeWizardHydrationDraft(d: Draft): void {
  sessionStorage.setItem(FACTORY_HYDRATE_SESSION_KEY, JSON.stringify(d));
}

export function readStoredWizardHydrationDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(FACTORY_HYDRATE_SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Draft;
  } catch {
    return null;
  }
}

export function clearStoredWizardHydrationDraft(): void {
  sessionStorage.removeItem(FACTORY_HYDRATE_SESSION_KEY);
}

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

export function canonicalKindSlugForDescriptor(desc: NodeDescriptor): string {
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

function ensurePorts(desc: NodeDescriptor): { inP: KindDraft["inputPorts"]; outP: KindDraft["outputPorts"] } {
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

/** Maps manifest default template paths to dropdown names (see `packageNodeLifecycle.tsx`). */
function sourceDisplayName(sourcePath: string | undefined): string | undefined {
  if (!sourcePath) return undefined;
  const basename = sourcePath.split("/").pop() ?? "";
  if (!basename) return undefined;
  const stem = basename.replace(/\.[^.]+$/u, "");
  return stem.replace(/_/g, " ");
}

/** Default source body for a palette kind, from the merged templates feed when available. */
export function packageKindSeedCode(desc: NodeDescriptor, getTemplates?: TemplatesLookup): string {
  if (!getTemplates || desc.source !== "package") return STARTER_CODE;
  const templates = [...getTemplates(desc.id, false)];
  const wanted = sourceDisplayName(desc.package?.source);
  const hit = wanted ? templates.find((t) => t.name === wanted) : templates[0];
  const body = typeof hit?.code === "string" ? hit.code : "";
  return body.trim().length ? body : STARTER_CODE;
}

function normalizeTemplateCode(body: string): string {
  return body.replace(/\r\n/g, "\n").trim();
}

/** Unique slug within `occupied` (`[a-z][a-z0-9-]…`). */
function forkKindSlugAwayFrom(baseSlug: string, occupied: ReadonlyMap<string, unknown>): string {
  for (let n = 0; n < 64; n++) {
    const leaf = normalizePackageIdLeaf(`${factoryUiMakeId()}${n}${baseSlug}`);
    let cand = `${baseSlug}-k-${leaf}`;
    if (cand.length > KIND_ID_SEGMENT_MAX_LEN) {
      cand = cand.slice(0, KIND_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "");
    }
    if (cand && /^[a-z][a-z0-9-]*$/u.test(cand) && !occupied.has(cand)) return cand;
  }
  const fallback = `${baseSlug}-k-${normalizePackageIdLeaf(factoryUiMakeId())}`;
  return fallback.length > KIND_ID_SEGMENT_MAX_LEN
    ? fallback.slice(0, KIND_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "")
    : fallback;
}

export function descriptorToKindDraft(
  desc: NodeDescriptor,
  code: string,
  kindIdOverride?: string,
  labelOverride?: string,
): KindDraft {
  const kindId = kindIdOverride ?? canonicalKindSlugForDescriptor(desc);
  const sourceFilename = inferSourceFilename(desc.package?.source);

  const { inP, outP } = ensurePorts(desc);

  return {
    id: kindId,
    label: labelOverride?.trim() || desc.label || kindId,
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

function nodesById(nodes: RFNode<any>[]): Map<string, RFNode<any>> {
  const map = new Map<string, RFNode<any>>();
  for (const n of nodes) map.set(String(n.id), n);
  return map;
}

export function normalizeKindLabel(label: string): string {
  return label.trim().toLowerCase();
}

/** Canvas-local kind title; falls back to registry descriptor label. */
export function canvasKindLabelFromNode(node: { data: object }, desc: NodeDescriptor): string {
  const raw = (node.data as { packageKindLabel?: unknown })?.packageKindLabel;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  return desc.label || canonicalKindSlugForDescriptor(desc);
}

/** True when the user set a canvas title that differs from the registry descriptor label. */
export function hasCustomCanvasKindLabel(node: { data: object }, desc: NodeDescriptor): boolean {
  const raw = (node.data as { packageKindLabel?: unknown })?.packageKindLabel;
  if (typeof raw !== "string" || !raw.trim()) return false;
  const registryLabel = desc.label || canonicalKindSlugForDescriptor(desc);
  return normalizeKindLabel(raw) !== normalizeKindLabel(registryLabel);
}

function kindDraftFromCanvasNode(
  node: RFNode<any>,
  desc: NodeDescriptor,
  body: string,
  kindIdOverride?: string,
): KindDraft {
  const label = canvasKindLabelFromNode(node, desc);
  const base = descriptorToKindDraft(desc, body, kindIdOverride, label);
  const config = readCanvasKindConfig(node);
  return applyCanvasKindConfigToKindDraft(base, config, label);
}

function findKindIdByLabel(kindsById: ReadonlyMap<string, KindDraft>, label: string): string | undefined {
  const norm = normalizeKindLabel(label);
  if (!norm) return undefined;
  for (const [id, kind] of kindsById) {
    if (normalizeKindLabel(kind.label) === norm) return id;
  }
  return undefined;
}

/**
 * Merge palette kinds currently installed (`seededDescriptors`) with edits from staged canvas nodes.
 * - Seeded rows use server default template bodies when available.
 * - Identical bodies under the same base slug produce separate kinds via fork ids so duplicate staged rows stay in the draft.
 * - Multiple staged implementations that share one base slug but differ in code also fork to unique IDs (`*-k-<leaf>`).
 */
export function mergeKindsForPaletteSave(
  seededDescriptors: readonly NodeDescriptor[],
  stagedOrdered: readonly RFNode<any>[],
  getTemplates?: TemplatesLookup,
): KindDraft[] | null {
  const kindsById = new Map<string, KindDraft>();
  const seededSlugs = new Set<string>();

  for (const desc of seededDescriptors) {
    const slug = canonicalKindSlugForDescriptor(desc);
    seededSlugs.add(slug);
    const seedBody = desc.source === "package" ? packageKindSeedCode(desc, getTemplates) : STARTER_CODE;
    kindsById.set(slug, descriptorToKindDraft(desc, seedBody));
  }

  for (const node of stagedOrdered) {
    const nt = getFlowNodeCanonicalType(node as RFNode);
    if (!nt) continue;
    const desc = tryGetNodeDescriptor(nt as NodeKindId);
    if (!desc) continue;
    const slugBase = canonicalKindSlugForDescriptor(desc);
    const body = runtimeCodeFromRfNode(node);
    const codeNorm = normalizeTemplateCode(body);
    const label = canvasKindLabelFromNode(node, desc);

    const labelMatchId = findKindIdByLabel(kindsById, label);
    if (labelMatchId) {
      kindsById.set(labelMatchId, kindDraftFromCanvasNode(node, desc, body, labelMatchId));
      continue;
    }

    if (hasCustomCanvasKindLabel(node, desc)) {
      const forkId = forkKindSlugAwayFrom(slugBase, kindsById);
      kindsById.set(forkId, kindDraftFromCanvasNode(node, desc, body, forkId));
      continue;
    }

    if (!kindsById.has(slugBase)) {
      kindsById.set(slugBase, kindDraftFromCanvasNode(node, desc, body, slugBase));
      continue;
    }

    const prev = kindsById.get(slugBase)!;
    if (normalizeTemplateCode(prev.sourceCode) === codeNorm) {
      const forkId = forkKindSlugAwayFrom(slugBase, kindsById);
      kindsById.set(forkId, kindDraftFromCanvasNode(node, desc, body, forkId));
      continue;
    }

    if (seededSlugs.has(slugBase)) {
      kindsById.set(slugBase, kindDraftFromCanvasNode(node, desc, body, slugBase));
      continue;
    }

    const forkId = forkKindSlugAwayFrom(slugBase, kindsById);
    kindsById.set(forkId, kindDraftFromCanvasNode(node, desc, body, forkId));
  }

  if (!kindsById.size) return null;
  return Array.from(kindsById.values()).sort((a, b) => a.id.localeCompare(b.id, undefined, { sensitivity: "base" }));
}

function freshForkPackageIdentity(sectionKey: string): { packageId: string; name: string; description: string } {
  const leaf = normalizePackageIdLeaf(`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);
  return {
    packageId: `curio.palette.fork.${leaf}`,
    name: `Palette fork (${sectionKey.replace(/[@/]/g, " · ")})`,
    description:
      "Created from the palette editor. Adjust metadata in the wizard, then reinstall or iterate from canvas drops.",
  };
}

/**
 * Hydrates **`/nodes/factory`** (`NodeFactoryRouteBridge`) using router state (`curioDraft`) and a
 * **`sessionStorage`** fallback for bookmarks / external tooling. Prefer **`useNodeFactoryModal().openNodeFactory`**
 * from TSX embedded in-app.
 */
export function navigateToFactoryWizard(navigate: NavigateFunction, draft: Draft): void {
  storeWizardHydrationDraft(draft);
  navigate("/nodes/factory", { state: { curioDraft: draft } });
}

/** Build a wizard `Draft` for Factory prefill / install-from-palette. Returns null when there is nothing to save. */
export function buildDraftForPaletteSection(opts: {
  sectionKey: string;
  stagedRows: readonly PackageStagedRow[];
  rfNodes: readonly RFNode<any>[];
  /** Pure canvas-draft section (`__draft__:uuid`). */
  standaloneDraft?: boolean;
  standalonePackageLeaf?: string;
  group?: PalettePackageGroupLite;
  /** Known installed package palette rows (`key` is `packageId@major`). Used to merge seeded kinds into canvas-draft saves. */
  palettePackageGroups?: readonly PalettePackageGroupLite[];
  getTemplates?: TemplatesLookup;
  /** Kind ids to omit from the seeded package when building the fork/draft. */
  removedKindIds?: readonly string[];
}): Draft | null {
  const {
    sectionKey,
    stagedRows,
    rfNodes,
    standaloneDraft,
    standalonePackageLeaf,
    group,
    palettePackageGroups,
    getTemplates,
    removedKindIds,
  } = opts;
  const removed = new Set((removedKindIds ?? []).map((id) => id.trim()).filter(Boolean));
  const byId = nodesById([...rfNodes]);
  const orderedStagedNodes = stagedRows
    .map((r) => byId.get(String(r.canvasNodeId)))
    .filter(Boolean) as RFNode<any>[];

  if (!orderedStagedNodes.length && removed.size === 0) return null;

  const draft = makeDraft();

  if (standaloneDraft) {
    if (!standalonePackageLeaf) return null;
    const stripped = standalonePackageLeaf.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
    const leaf = normalizePackageIdLeaf(stripped || standalonePackageLeaf);
    draft.packageId = `curio.canvas.draft.${leaf}`;
    draft.name = "New canvas package";
    draft.publisher = "Local palette";
    draft.description = `Draft assembled from staged canvas nodes (${sectionKey}). Refine identity in the wizard if needed.`;
  } else if (group) {
    const meta = freshForkPackageIdentity(sectionKey);
    draft.packageId = meta.packageId;
    draft.name = meta.name;
    draft.publisher = group.descriptors[0]?.package?.publisher?.trim()
      ? String(group.descriptors[0]?.package?.publisher)
      : "Palette editor fork";
    draft.description = meta.description;
    draft.major = group.descriptors[0]?.package?.major ?? draft.major;
    const lineageDraft = lineageDraftForInstalledPackageGroup(group);
    if (lineageDraft) {
      draft.lineage = lineageDraft;
    }
  } else {
    return null;
  }

  const coord = `${draft.packageId}@${draft.major}`;
  const seededDescriptors: readonly NodeDescriptor[] = (
    group?.descriptors
      ? group.descriptors
      : palettePackageGroups?.find((g) => g.key === coord)?.descriptors ?? []
  ).filter((d) => !removed.has(d.id));

  const mergedKinds = mergeKindsForPaletteSave(seededDescriptors, orderedStagedNodes, getTemplates);
  if (!mergedKinds?.length) return null;
  draft.kinds = mergedKinds;

  return draft;
}

function categoryFromPackageKind(cat: string): Category {
  return WIZARD_CATEGORIES.has(cat) ? (cat as Category) : "computation";
}

function depsRows(record: Record<string, string>): { id: string; pkg: string; range: string }[] {
  return Object.entries(record).map(([pkg, range]) => ({
    id: factoryUiMakeId(),
    pkg,
    range: range ?? "*",
  }));
}

function seedCodeForPackageKindPayload(kind: PackageKindPayload, getTemplates?: TemplatesLookup): string {
  if (!getTemplates) return STARTER_CODE;
  const templates = [...getTemplates(kind.id as NodeKindId, false)];
  const wanted = sourceDisplayName(kind.source ?? undefined);
  const hit = wanted ? templates.find((t) => t.name === wanted) : templates[0];
  const body = typeof hit?.code === "string" ? hit.code : "";
  return body.trim().length ? body : STARTER_CODE;
}

function packageKindPayloadToKindDraft(kind: PackageKindPayload, getTemplates?: TemplatesLookup): KindDraft {
  const sourceFilename =
    kind.source?.split("/").pop()?.trim() || `${kind.kindId}.py`;
  const inputPorts =
    kind.inputPorts?.map((p) => ({
      id: factoryUiMakeId(),
      types: (p.types ?? []).join(","),
      cardinality: String(p.cardinality ?? "1"),
    })) ?? [];
  const outputPortsRaw =
    kind.outputPorts?.length ?
      kind.outputPorts.map((p) => ({
        id: factoryUiMakeId(),
        types: (p.types ?? []).join(","),
        cardinality: String(p.cardinality ?? "1"),
      }))
    : [{ id: factoryUiMakeId(), types: "JSON", cardinality: "1" }];
  const engine: Engine = kind.engine === "javascript" ? "javascript" : "python";
  return {
    id: kind.kindId,
    label: kind.label || kind.kindId,
    category: categoryFromPackageKind(kind.category),
    engine,
    editor: kind.editor,
    description: kind.description ?? "",
    hasCode: !!kind.hasCode,
    hasWidgets: !!kind.hasWidgets,
    hasGrammar: !!kind.hasGrammar,
    inputPorts,
    outputPorts: outputPortsRaw,
    lifecycle: kind.lifecycle ?? undefined,
    iconRef: kind.iconRef ?? undefined,
    paletteOrder: typeof kind.paletteOrder === "number" ? kind.paletteOrder : undefined,
    sourceFilename,
    sourceCode: seedCodeForPackageKindPayload(kind, getTemplates),
  };
}

/** Factory draft from ``GET /api/packages`` row — used for palette “publish to catalog”. */
export function draftFromInstalledPackagePayload(
  pkg: PackagePayload,
  getTemplates?: TemplatesLookup,
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
  d.kinds = pkg.kinds.map((k) => packageKindPayloadToKindDraft(k, getTemplates));
  if (typeof pkg.createdAt === "string" && pkg.createdAt.trim()) {
    d.createdAt = pkg.createdAt.trim();
  }
  return d;
}

export const SAVE_AS_NEW_PACK = "__save_as_new__";

/** True when Save As into `package` would overwrite an existing kind with the same label. */
export function saveAsWouldReplaceByLabel(pkg: PackagePayload, nodeLabel: string): boolean {
  const norm = normalizeKindLabel(nodeLabel);
  if (!norm) return false;
  return pkg.kinds.some((k) => normalizeKindLabel(k.label) === norm);
}

/** Build a factory install draft when saving a single canvas node into a package (Save As). */
export function buildSaveAsInstallDraft(opts: {
  canvasNode: RFNode<any>;
  target:
    | { kind: "new"; packageDisplayName?: string }
    | { kind: "installed"; pkg: PackagePayload };
  getTemplates?: TemplatesLookup;
}): Draft | null {
  const nt = getFlowNodeCanonicalType(opts.canvasNode as RFNode);
  if (!nt) return null;
  const desc = tryGetNodeDescriptor(nt as NodeKindId);
  if (!desc) return null;

  const label = canvasKindLabelFromNode(opts.canvasNode, desc);
  const body = runtimeCodeFromRfNode(opts.canvasNode);
  const slugBase = canonicalKindSlugForDescriptor(desc);

  if (opts.target.kind === "new") {
    const leaf = normalizePackageIdLeaf(factoryUiMakeId());
    const draft = makeDraft();
    draft.packageId = `curio.canvas.draft.${leaf}`;
    draft.name = opts.target.packageDisplayName?.trim() || `${label} package`;
    draft.publisher = "Local palette";
    draft.description = "Created from canvas Save As.";
    draft.kinds = [kindDraftFromCanvasNode(opts.canvasNode, desc, body, slugBase)];
    return draft;
  }

  const draft = draftFromInstalledPackagePayload(opts.target.package, opts.getTemplates);

  const labelMatchIdx = draft.kinds.findIndex(
    (k) => normalizeKindLabel(k.label) === normalizeKindLabel(label),
  );
  if (labelMatchIdx >= 0) {
    const existingId = draft.kinds[labelMatchIdx]!.id;
    draft.kinds[labelMatchIdx] = kindDraftFromCanvasNode(opts.canvasNode, desc, body, existingId);
    return draft;
  }

  const kindsMap = new Map(draft.kinds.map((k) => [k.id, k]));
  const kindId = kindsMap.has(slugBase) ? forkKindSlugAwayFrom(slugBase, kindsMap) : slugBase;
  draft.kinds.push(kindDraftFromCanvasNode(opts.canvasNode, desc, body, kindId));
  return draft;
}

/** True when the draft was opened as a fork-from-installed flow (new coord + lineage). */
export function isForkFromInstalledDraft(draft: Draft): boolean {
  const lin = draft.lineage;
  if (!lin) return false;
  const source = `${lin.forkedFrom.packageId}@${lin.forkedFrom.major}`;
  const self = `${draft.packageId}@${draft.major}`;
  return source !== self;
}

/**
 * Full wizard prefill from an installed package, but with a **new** fork coordinate and lineage
 * so factory install never overwrites the source directory.
 */
export function draftForkFromInstalledPackagePayload(
  pkg: PackagePayload,
  getTemplates?: TemplatesLookup,
): Draft {
  const d = draftFromInstalledPackagePayload(pkg, getTemplates);
  const idMeta = freshForkPackageIdentity(`${pkg.packageId}@${pkg.major}`);
  d.packageId = idMeta.packageId;
  d.name = `Fork of ${pkg.name}`;
  d.description = `Forked from ${pkg.packageId}@${pkg.major}. ${pkg.description ?? ""}`.trim();
  d.major = pkg.major;
  const forkedFrom = { packageId: pkg.packageId, major: pkg.major };
  const anchor = pkg.lineage?.root;
  const root = anchor
    ? { packageId: anchor.packageId, major: anchor.major }
    : forkedFrom;
  d.lineage = { forkedFrom, root };
  delete d.createdAt;
  return d;
}
