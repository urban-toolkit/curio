/**
 * A collection's files, read through the dataflow of the canvas.
 *
 * The backend serves a collection's files by id, `/api/datasets/<id>/media/<file>`.
 * With `dataflowId`, it also finds a collection that dataflow lists, from its
 * owner's store, for the owner and an editor she invited
 * (`DiscoveryService.collection`): what an invited editor's canvas needs to
 * show the owner's collection. Anyone else gets what no dataflow gives.
 *
 * A file a dashboard viewer's step derived is in a folder of that step's own,
 * which the URL of its row names (`?kept=<name>`, `sandbox/util/collections.py`):
 * every read of the file names it too.
 */

const COLLECTION_MEDIA = /^\/api\/datasets\/[^/?#]+\/media\//;

/** One file of a collection, as the URL of a row names it. */
const COLLECTION_MEDIA_FILE = /^\/api\/datasets\/([^/?#]+)\/media\/([^/?#]+)(?:\?([^#]*))?$/;

/** *path*, a same-origin `/api/` path, read through *dataflowId*. Unchanged
 *  with no dataflow, and for a path that names no collection's file. */
export function collectionMediaPath(path: string, dataflowId: string | null | undefined): string {
  if (!dataflowId || !COLLECTION_MEDIA.test(path)) return path;
  return `${path}${path.includes("?") ? "&" : "?"}dataflowId=${encodeURIComponent(dataflowId)}`;
}

/** The file a row's media URL names: its collection, its id, the variant it
 *  asks for, and the folder of the dashboard viewer's step that derived it. */
export interface CollectionMediaRef {
  datasetId: string;
  fileId: string;
  variant: string | null;
  kept: string | null;
}

/** The file *path* names, or null for a path that names no collection's file. */
export function collectionMediaRef(path: unknown): CollectionMediaRef | null {
  if (typeof path !== "string") return null;
  const found = COLLECTION_MEDIA_FILE.exec(path);
  if (!found) return null;
  const query = new URLSearchParams(found[3] ?? "");
  return {
    datasetId: decodeURIComponent(found[1]),
    fileId: decodeURIComponent(found[2]),
    variant: query.get("variant"),
    kept: query.get("kept"),
  };
}

/** The first of *row*'s media URLs that names its file *fileId* of
 *  *datasetId* (its thumbnail, say), which names the folder of the dashboard
 *  viewer's step that derived it too; null when none does. */
export function mediaPathOfRow(row: Record<string, unknown>, datasetId: string, fileId: string): string | null {
  for (const value of Object.values(row)) {
    const ref = collectionMediaRef(value);
    if (ref && ref.datasetId === datasetId && ref.fileId === fileId) return value as string;
  }
  return null;
}
