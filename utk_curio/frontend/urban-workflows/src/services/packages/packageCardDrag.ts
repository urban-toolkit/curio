import { packageKindOf } from "./modelPackages";
import type { PackageKind, PackagePayload } from "./types";

/**
 * A package's card dragged from the Node Catalog drawer onto the canvas,
 * where it becomes one of the package's nodes: its one node, or the node
 * picked from a menu of its nodes at the drop point. A card drags when its
 * package has a node.
 */

/** A node a card's drop can make. */
export interface PackageCardNode {
  /** The node's canonical type, `<packageId>/<templateId>@<major>`. */
  nodeType: string;
  label: string;
}

/** What a card drag carries: the package, and the nodes its drop can make. */
export interface PackageCardDragPayload {
  dirName: string;
  name: string;
  kind: PackageKind;
  /** In the palette's order: the drop makes the one, or offers several in a menu. */
  nodes: PackageCardNode[];
}

export const PACKAGE_CARD_DRAG_MIME = "application/x-curio-package-card";
const PACKAGE_CARD_DRAG_PLAIN_PREFIX = "curio-package-card:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activePackageCardDrag: PackageCardDragPayload | null = null;

/** The nodes a drop of *pkg*'s card can make: every node of the package, in
 *  the palette's order (`paletteOrder`, the manifest's order among equals). */
export function packageCardNodes(
  pkg: Pick<PackagePayload, "templates">,
): PackageCardNode[] {
  return [...pkg.templates]
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999))
    .map((template) => ({ nodeType: template.id, label: template.label }));
}

/** The drag of *pkg*'s card, or `null` when the card does not drag: its package has no node. */
export function createPackageCardDragPayload(pkg: PackagePayload): PackageCardDragPayload | null {
  const nodes = packageCardNodes(pkg);
  if (nodes.length === 0) return null;
  return {
    dirName: pkg.dirName,
    name: pkg.name,
    kind: packageKindOf(pkg),
    nodes,
  };
}

function isCardNode(node: unknown): node is PackageCardNode {
  const { nodeType, label } = (node ?? {}) as Partial<PackageCardNode>;
  return typeof nodeType === "string" && nodeType !== "" && typeof label === "string";
}

function parsePackageCardDragJson(raw: string): PackageCardDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<PackageCardDragPayload>;
    if (!payload.dirName || !payload.name) return null;
    if (!Array.isArray(payload.nodes) || payload.nodes.length === 0 || !payload.nodes.every(isCardNode)) {
      return null;
    }
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
