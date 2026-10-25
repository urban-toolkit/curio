/**
 * Where a page reads an output while a dataflow is open on it: that
 * dataflow's output routes (`projects/routes.py`), which read the store under
 * the caller's session and, for an output the dataflow saved, the file its
 * owner's Data Catalog keeps, in place, with nothing copied.
 *
 * `ProjectLoader` sets the open dataflow: the one the route opened, the
 * owner's or a shared one, or the id a new dataflow gets on its first save.
 * A canvas with none reads `/get` and `/raster` as before. A dashboard page
 * reads what it carries, and its viewers' kept files
 * (`runs/dashboardRunFiles.ts`), first: `fetchData`, `fetchPreviewData` and
 * `fetchRaster` (`services/api.ts`) ask about those before this.
 */
import { backendUrl } from "../utils/backendUrl";
import type { DashboardRead } from "./runs/dashboardRunFiles";

let openDataflow: string | null = null;

/** The dataflow whose outputs the canvas reads from now on, or none. */
export function setOpenDataflow(projectId: string | null | undefined): void {
    openDataflow = projectId || null;
}

/** The dataflow the canvas reads its outputs on, or null. */
export function openDataflowId(): string | null {
    return openDataflow;
}

/**
 * The address a read of an output goes to on the open dataflow's route, with
 * *query* (its `fileName` included), or undefined when no dataflow is open.
 */
export function dataflowRead(read: DashboardRead, query: URLSearchParams): string | undefined {
    if (!openDataflow) return undefined;
    const path = `/api/projects/${encodeURIComponent(openDataflow)}/outputs/${read}`;
    return `${backendUrl()}${path}?${query.toString()}`;
}
