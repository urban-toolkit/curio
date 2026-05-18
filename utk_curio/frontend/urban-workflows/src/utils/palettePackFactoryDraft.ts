import { Node as RFNode } from "reactflow";
import type { NavigateFunction } from "react-router-dom";
import type { PackKindPayload, PackPayload } from "../api/packsApi";
import { NodeDescriptor } from "../registry/types";
import { NodeKindId } from "../registry/types";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import { getFlowNodeCanonicalType } from "./flowNodeCanonicalType";
import type { PackStagedRow } from "../providers/PackPaletteContext";
import {
  Draft,
  KindDraft,
  Category,
  Engine,
  makeDraft,
  factoryUiMakeId,
  STARTER_CODE,
  toApiPayload,
  type PackLineageDraft,
} from "../pages/nodes/factoryDraftModel";

export const FACTORY_HYDRATE_SESSION_KEY = "curio.factoryWizardHydrateDraft.v1";

/** Matches `PackId` segment rules (`PACK_DIR_RE` in `utk_curio.backend.app.packs.storage`). */
const PACK_ID_SEGMENT_MAX_LEN = 63;

/** Mirrors backend `KIND_ID_RE` (`utk_curio.backend.app.packs.storage`). */
const KIND_ID_SEGMENT_MAX_LEN = 63;

const WIZARD_CATEGORIES = new Set<string>(["data", "computation", "vis_grammar", "vis_simple", "flow"]);

export type TemplatesLookup = (type: NodeKindId, custom: boolean) => readonly { name: string; code: string }[];

/**
 * Normalizes arbitrary input into a single valid reverse‑DNS trailing segment (`[a-z][a-z0-9-]{0,62}`).
 * UUID hex without hyphens often starts with `0‑9`; those are prefixed so factory install validates.
 */
export function normalizePackIdLeaf(raw: string): string {
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

export type PalettePackGroupLite = {
  key: string;
  label: string;
  descriptors: NodeDescriptor[];
};

/**
 * Parse a palette section key ``<packId>@<major>`` (used for installed packs).
 * Returns null for draft sections (``__draft__:…``) or malformed keys.
 */
export function parsePalettePackSectionKey(key: string): { packId: string; major: number } | null {
  const at = key.lastIndexOf("@");
  if (at <= 0) return null;
  const packId = key.slice(0, at).trim();
  const majorRaw = key.slice(at + 1).trim();
  if (!packId || !majorRaw) return null;
  const major = Number(majorRaw);
  if (!Number.isInteger(major) || major < 0) return null;
  return { packId, major };
}

function lineageDraftForInstalledPackGroup(group: PalettePackGroupLite): PackLineageDraft | null {
  const forkedFrom = parsePalettePackSectionKey(group.key);
  if (!forkedFrom) return null;
  const anchor = group.descriptors[0]?.pack?.lineage?.root;
  const root = anchor ? { packId: anchor.packId, major: anchor.major } : forkedFrom;
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
 * Payload for POST `/api/packs/factory/install`.
 * When `replace` is true the backend **replaces the installed pack directory** (`packId@major`)
 * so the **Packs palette** picks up the new manifest. It does **not** modify nodes on the canvas.
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

function inferDefaultFilename(packRelativePath?: string): string {
  if (!packRelativePath) return "Default.py";
  const parts = packRelativePath.split("/").filter(Boolean);
  const last = parts[parts.length - 1];
  return last.endsWith(".py") ? last : "Default.py";
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

/** Maps manifest default template paths to dropdown names (see `packNodeLifecycle.tsx`). */
function defaultTemplateDisplayName(defaultTemplatePath: string | undefined): string | undefined {
  if (!defaultTemplatePath) return undefined;
  const basename = defaultTemplatePath.split("/").pop() ?? "";
  if (!basename) return undefined;
  const stem = basename.replace(/\.py$/i, "").replace(/\.js$/i, "");
  return stem.replace(/_/g, " ");
}

/** Default template Python/JS body for a palette kind, from the merged templates feed when available. */
export function packKindSeedCode(desc: NodeDescriptor, getTemplates?: TemplatesLookup): string {
  if (!getTemplates || desc.source !== "pack") return STARTER_CODE;
  const templates = [...getTemplates(desc.id, false)];
  const wanted = defaultTemplateDisplayName(desc.pack?.defaultTemplate);
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
    const leaf = normalizePackIdLeaf(`${factoryUiMakeId()}${n}${baseSlug}`);
    let cand = `${baseSlug}-k-${leaf}`;
    if (cand.length > KIND_ID_SEGMENT_MAX_LEN) {
      cand = cand.slice(0, KIND_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "");
    }
    if (cand && /^[a-z][a-z0-9-]*$/u.test(cand) && !occupied.has(cand)) return cand;
  }
  const fallback = `${baseSlug}-k-${normalizePackIdLeaf(factoryUiMakeId())}`;
  return fallback.length > KIND_ID_SEGMENT_MAX_LEN
    ? fallback.slice(0, KIND_ID_SEGMENT_MAX_LEN).replace(/-+$/u, "")
    : fallback;
}

export function descriptorToKindDraft(desc: NodeDescriptor, code: string, kindIdOverride?: string): KindDraft {
  const kindId = kindIdOverride ?? canonicalKindSlugForDescriptor(desc);
  const fname = inferDefaultFilename(desc.pack?.defaultTemplate);

  const { inP, outP } = ensurePorts(desc);
  const templateDir = `templates/${kindId}`;
  const defaultTemplate = `${templateDir}/${fname}`;

  return {
    id: kindId,
    label: desc.label || kindId,
    category: desc.category as Category,
    engine: deriveEngine(desc),
    editor: desc.editor,
    description: desc.description ?? "",
    hasCode: !!desc.hasCode,
    hasWidgets: !!desc.hasWidgets,
    hasGrammar: !!desc.hasGrammar,
    inputPorts: inP,
    outputPorts: outP,
    templateDir,
    defaultTemplate,
    defaultTemplateName: fname,
    defaultTemplateCode: code?.trim()?.length ? code : STARTER_CODE,
  };
}

function nodesById(nodes: RFNode<any>[]): Map<string, RFNode<any>> {
  const map = new Map<string, RFNode<any>>();
  for (const n of nodes) map.set(String(n.id), n);
  return map;
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
    const seedBody = desc.source === "pack" ? packKindSeedCode(desc, getTemplates) : STARTER_CODE;
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

    if (!kindsById.has(slugBase)) {
      kindsById.set(slugBase, descriptorToKindDraft(desc, body));
      continue;
    }

    const prev = kindsById.get(slugBase)!;
    if (normalizeTemplateCode(prev.defaultTemplateCode) === codeNorm) {
      const forkId = forkKindSlugAwayFrom(slugBase, kindsById);
      kindsById.set(forkId, descriptorToKindDraft(desc, body, forkId));
      continue;
    }

    if (seededSlugs.has(slugBase)) {
      kindsById.set(slugBase, descriptorToKindDraft(desc, body));
      continue;
    }

    const forkId = forkKindSlugAwayFrom(slugBase, kindsById);
    kindsById.set(forkId, descriptorToKindDraft(desc, body, forkId));
  }

  if (!kindsById.size) return null;
  return Array.from(kindsById.values()).sort((a, b) => a.id.localeCompare(b.id, undefined, { sensitivity: "base" }));
}

function freshForkPackIdentity(sectionKey: string): { packId: string; name: string; description: string } {
  const leaf = normalizePackIdLeaf(`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);
  return {
    packId: `curio.palette.fork.${leaf}`,
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
  stagedRows: readonly PackStagedRow[];
  rfNodes: readonly RFNode<any>[];
  /** Pure canvas-draft section (`__draft__:uuid`). */
  standaloneDraft?: boolean;
  standalonePackLeaf?: string;
  group?: PalettePackGroupLite;
  /** Known installed pack palette rows (`key` is `packId@major`). Used to merge seeded kinds into canvas-draft saves. */
  palettePackGroups?: readonly PalettePackGroupLite[];
  getTemplates?: TemplatesLookup;
}): Draft | null {
  const { sectionKey, stagedRows, rfNodes, standaloneDraft, standalonePackLeaf, group, palettePackGroups, getTemplates } = opts;
  const byId = nodesById([...rfNodes]);
  const orderedStagedNodes = stagedRows
    .map((r) => byId.get(String(r.canvasNodeId)))
    .filter(Boolean) as RFNode<any>[];

  if (!orderedStagedNodes.length) return null;

  const draft = makeDraft();

  if (standaloneDraft) {
    if (!standalonePackLeaf) return null;
    const stripped = standalonePackLeaf.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
    const leaf = normalizePackIdLeaf(stripped || standalonePackLeaf);
    draft.packId = `curio.canvas.draft.${leaf}`;
    draft.name = "New canvas pack";
    draft.publisher = "Local palette";
    draft.description = `Draft assembled from staged canvas nodes (${sectionKey}). Refine identity in the wizard if needed.`;
  } else if (group) {
    const meta = freshForkPackIdentity(sectionKey);
    draft.packId = meta.packId;
    draft.name = meta.name;
    draft.publisher = group.descriptors[0]?.pack?.publisher?.trim()
      ? String(group.descriptors[0]?.pack?.publisher)
      : "Palette editor fork";
    draft.description = meta.description;
    draft.major = group.descriptors[0]?.pack?.major ?? draft.major;
    const lineageDraft = lineageDraftForInstalledPackGroup(group);
    if (lineageDraft) {
      draft.lineage = lineageDraft;
    }
  } else {
    return null;
  }

  const coord = `${draft.packId}@${draft.major}`;
  const seededDescriptors: readonly NodeDescriptor[] = group?.descriptors
    ? group.descriptors
    : palettePackGroups?.find((g) => g.key === coord)?.descriptors ?? [];

  const mergedKinds = mergeKindsForPaletteSave(seededDescriptors, orderedStagedNodes, getTemplates);
  if (!mergedKinds?.length) return null;
  draft.kinds = mergedKinds;

  return draft;
}

function categoryFromPackKind(cat: string): Category {
  return WIZARD_CATEGORIES.has(cat) ? (cat as Category) : "computation";
}

function depsRows(record: Record<string, string>): { id: string; pkg: string; range: string }[] {
  return Object.entries(record).map(([pkg, range]) => ({
    id: factoryUiMakeId(),
    pkg,
    range: range ?? "*",
  }));
}

function seedCodeForPackKindPayload(kind: PackKindPayload, getTemplates?: TemplatesLookup): string {
  if (!getTemplates) return STARTER_CODE;
  const templates = [...getTemplates(kind.id as NodeKindId, false)];
  const wanted = defaultTemplateDisplayName(kind.defaultTemplate ?? undefined);
  const hit = wanted ? templates.find((t) => t.name === wanted) : templates[0];
  const body = typeof hit?.code === "string" ? hit.code : "";
  return body.trim().length ? body : STARTER_CODE;
}

function packKindPayloadToKindDraft(kind: PackKindPayload, getTemplates?: TemplatesLookup): KindDraft {
  const defaultTemplate =
    kind.defaultTemplate?.trim() || `templates/${kind.kindId}/Default.py`;
  const defaultTemplateName = defaultTemplate.split("/").pop() || "Default.py";
  const templateDir = kind.templateDir?.trim() || `templates/${kind.kindId}`;
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
    category: categoryFromPackKind(kind.category),
    engine,
    editor: kind.editor,
    description: kind.description ?? "",
    hasCode: !!kind.hasCode,
    hasWidgets: !!kind.hasWidgets,
    hasGrammar: !!kind.hasGrammar,
    inputPorts,
    outputPorts: outputPortsRaw,
    templateDir,
    defaultTemplate,
    defaultTemplateName,
    defaultTemplateCode: seedCodeForPackKindPayload(kind, getTemplates),
  };
}

/** Factory draft from ``GET /api/packs`` row — used for palette “publish to catalog”. */
export function draftFromInstalledPackPayload(
  pack: PackPayload,
  getTemplates?: TemplatesLookup,
): Draft {
  const d = makeDraft();
  d.packId = pack.packId;
  d.major = pack.major;
  d.version = pack.version;
  d.name = pack.name;
  d.publisher = pack.publisher;
  d.description = pack.description;
  d.license = pack.license ?? "MIT";
  d.permissions = [...pack.permissions];
  d.pythonDeps = depsRows(pack.dependencies.python ?? {});
  d.jsDeps = depsRows(pack.dependencies.js ?? {});
  d.packDeps = depsRows(pack.dependencies.packs ?? {});
  d.lineage = pack.lineage
    ? {
        forkedFrom: {
          packId: pack.lineage.forkedFrom.packId,
          major: pack.lineage.forkedFrom.major,
        },
        root: {
          packId: pack.lineage.root.packId,
          major: pack.lineage.root.major,
        },
      }
    : null;
  d.kinds = pack.kinds.map((k) => packKindPayloadToKindDraft(k, getTemplates));
  if (typeof pack.createdAt === "string" && pack.createdAt.trim()) {
    d.createdAt = pack.createdAt.trim();
  }
  return d;
}

/** True when the draft was opened as a fork-from-installed flow (new coord + lineage). */
export function isForkFromInstalledDraft(draft: Draft): boolean {
  const lin = draft.lineage;
  if (!lin) return false;
  const source = `${lin.forkedFrom.packId}@${lin.forkedFrom.major}`;
  const self = `${draft.packId}@${draft.major}`;
  return source !== self;
}

/**
 * Full wizard prefill from an installed pack, but with a **new** fork coordinate and lineage
 * so factory install never overwrites the source directory.
 */
export function draftForkFromInstalledPackPayload(
  pack: PackPayload,
  getTemplates?: TemplatesLookup,
): Draft {
  const d = draftFromInstalledPackPayload(pack, getTemplates);
  const idMeta = freshForkPackIdentity(`${pack.packId}@${pack.major}`);
  d.packId = idMeta.packId;
  d.name = `Fork of ${pack.name}`;
  d.description = `Forked from ${pack.packId}@${pack.major}. ${pack.description ?? ""}`.trim();
  d.major = pack.major;
  const forkedFrom = { packId: pack.packId, major: pack.major };
  const anchor = pack.lineage?.root;
  const root = anchor
    ? { packId: anchor.packId, major: anchor.major }
    : forkedFrom;
  d.lineage = { forkedFrom, root };
  delete d.createdAt;
  return d;
}
