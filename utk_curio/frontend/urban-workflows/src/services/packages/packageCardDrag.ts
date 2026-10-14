import { packageKindOf } from "./modelPackages";
import type { PackageKind, PackagePayload } from "./types";

/**
 * A package's card dragged from the Node Catalog drawer onto the canvas,
 * where it becomes the package's node. A card drags when its package has
 * one node, which is the node its drop makes.
 */

/** What a card drag carries: the package, and the node its drop makes. */
export interface PackageCardDragPayload {
  dirName: string;
  name: string;
  kind: PackageKind;
  /** The node's canonical type, `<packageId>/<templateId>@<major>`. */
  nodeType: string;
  nodeLabel: string;
}

export const PACKAGE_CARD_DRAG_MIME = "application/x-curio-package-card";
const PACKAGE_CARD_DRAG_PLAIN_PREFIX = "curio-package-card:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activePackageCardDrag: PackageCardDragPayload | null = null;

/** The node a drop of *pkg*'s card makes: its one node, or none. */
export function packageCardNode(
  pkg: Pick<PackagePayload, "templates">,
): { nodeType: string; label: string } | null {
  if (pkg.templates.length !== 1) return null;
  const [template] = pkg.templates;
  return { nodeType: template.id, label: template.label };
}

/** The drag of *pkg*'s card, or `null` when the card does not drag. */
export function createPackageCardDragPayload(pkg: PackagePayload): PackageCardDragPayload | null {
  const node = packageCardNode(pkg);
  if (!node) return null;
  return {
    dirName: pkg.dirName,
    name: pkg.name,
    kind: packageKindOf(pkg),
    nodeType: node.nodeType,
    nodeLabel: node.label,
  };
}

function parsePackageCardDragJson(raw: string): PackageCardDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<PackageCardDragPayload>;
    if (!payload.dirName || !payload.name || !payload.nodeType || !payload.nodeLabel) return null;
    return { kind: "node", ...payload } as PackageCardDragPayload;
  } catch {
    return null;
  }
}

/** Call from `dragStart` on a card. */
export function beginPackageCardDrag(pkg: PackagePayload): PackageCardDragPayload | null {
  activePackageCardDrag = createPackageCardDragPayload(pkg);
  return activePackageCardDrag;
}

/** Call from `dragEnd`, and once a drop has read the payload, so a stale one is not reused. */
export function endPackageCardDrag(): void {
  activePackageCardDrag = null;
}

/** Write drag data (custom MIME + text/plain fallback for the drop handler). */
export function writePackageCardDragData(dataTransfer: DataTransfer, payload: PackageCardDragPayload): void {
  const json = JSON.stringify(payload);
  dataTransfer.setData(PACKAGE_CARD_DRAG_MIME, json);
  dataTransfer.setData("text/plain", `${PACKAGE_CARD_DRAG_PLAIN_PREFIX}${json}`);
  dataTransfer.effectAllowed = "copy";
}

export function readPackageCardDragPayload(dataTransfer: DataTransfer): PackageCardDragPayload | null {
  if (activePackageCardDrag) return activePackageCardDrag;
  const fromMime = parsePackageCardDragJson(dataTransfer.getData(PACKAGE_CARD_DRAG_MIME));
  if (fromMime) return fromMime;
  const plain = dataTransfer.getData("text/plain");
  if (plain.startsWith(PACKAGE_CARD_DRAG_PLAIN_PREFIX)) {
    return parsePackageCardDragJson(plain.slice(PACKAGE_CARD_DRAG_PLAIN_PREFIX.length));
  }
  return null;
}

export function hasPackageCardDrag(dataTransfer: DataTransfer): boolean {
  if (activePackageCardDrag) return true;
  const types = Array.from(dataTransfer.types || []);
  return types.includes(PACKAGE_CARD_DRAG_MIME);
}
