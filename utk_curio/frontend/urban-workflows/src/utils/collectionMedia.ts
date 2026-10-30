/**
 * A collection's files, read through the dataflow of the canvas.
 *
 * The backend serves a collection's files by id, `/api/datasets/<id>/media/<file>`.
 * With `dataflowId`, it also finds a collection that dataflow lists, from its
 * owner's store, for the owner and an editor she invited
 * (`DiscoveryService.collection`): what an invited editor's canvas needs to
 * show the owner's collection. Anyone else gets what no dataflow gives.
 */

const COLLECTION_MEDIA = /^\/api\/datasets\/[^/?#]+\/media\//;

/** *path*, a same-origin `/api/` path, read through *dataflowId*. Unchanged
 *  with no dataflow, and for a path that names no collection's file. */
export function collectionMediaPath(path: string, dataflowId: string | null | undefined): string {
  if (!dataflowId || !COLLECTION_MEDIA.test(path)) return path;
  return `${path}${path.includes("?") ? "&" : "?"}dataflowId=${encodeURIComponent(dataflowId)}`;
}
