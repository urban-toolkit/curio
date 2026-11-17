/**
 * The files a dashboard's tiles show, read through links the dashboard signs
 * (#1117; backend `POST /api/projects/<id>/dashboard/media`,
 * `projects/services.dashboard_media_links`). The media route needs a sign-in
 * and reads the caller's own collections, so a dashboard's page, whoever
 * opens it, signed in or not, reads a tile's images and videos through these
 * instead: `/api/media/<token>`, with `?variant=` for a thumbnail or a
 * poster.
 *
 * `fetchData` and `fetchPreviewData` (`services/api.ts`) note every output
 * the page reads that the dashboard carries or a viewer's run made
 * (`noteDashboardOutput`), with the files its rows name. A Simple View card,
 * or its player, then asks for the link of a file one of them names
 * (`dashboardMediaLink`), and the cards drawn at once ask in one request per
 * output. A link lives as long as the answer says; one about to lapse is
 * asked for again. A file no such output names is read as on the canvas.
 */
import { apiFetch } from "../../utils/authApi";
import { collectionMediaRef } from "../../utils/collectionMedia";
import { embeddedArtifact, getEmbeddedDashboard } from "../../standalone/dashboardPayload";
import { dashboardRunProject } from "./dashboardRunFiles";

/** A link this close to its lapse, or past it, is asked for again. */
export const LINK_LAPSE_MARGIN_MS = 60_000;

/** The most files one request names: the backend's `MAX_DASHBOARD_MEDIA_FILES`. */
const FILES_PER_ASK = 500;

/** One file, as a row's URL names it and the dashboard answers it. */
interface MediaFile {
  datasetId: string;
  fileId: string;
  kept: string | null;
}

/** The output whose rows name a file, on the dashboard it is read on. */
interface Holder {
  projectId: string;
  fileName: string;
}

/** A file's link, or none (`url` null: the dashboard gave none), until it lapses. */
interface Kept {
  url: string | null;
  lapsesAt: number;
}

/** What the dashboard answers an ask with: the links it gives, and their life in seconds. */
interface LinksAnswer {
  links?: Array<MediaFile & { url: string }>;
  expiresIn?: number;
}

/** A link to one file, by this page's clock. */
export interface DashboardMediaLink {
  /** A same-origin path: `/api/media/<token>?variant=<variant>`. */
  url: string;
  lapsesAt: number;
}

/** Which output names each file, the latest read. */
const holders = new Map<string, Holder>();
/** Each file's link, once asked. */
const links = new Map<string, Kept>();
/** The files waiting for the next request, by output, and its answer. */
const waiting = new Map<string, { holder: Holder; files: Map<string, MediaFile>; answered: Promise<void> }>();

function keyOf(file: MediaFile): string {
  return `${file.datasetId}/${file.fileId}/${file.kept ?? ""}`;
}

/** Every file the media URLs anywhere in *value*, an output's envelope, name,
 *  as the backend finds them (`collections.media_refs`). A feature's
 *  `geometry` holds no URL, and is not read. */
function filesNamedIn(value: unknown): MediaFile[] {
  const found = new Map<string, MediaFile>();
  const stack: unknown[] = [value];
  while (stack.length > 0) {
    const item = stack.pop();
    if (typeof item === "string") {
      if (!item.startsWith("/api/datasets/")) continue;
      const ref = collectionMediaRef(item);
      if (ref) {
        const file = { datasetId: ref.datasetId, fileId: ref.fileId, kept: ref.kept };
        found.set(keyOf(file), file);
      }
    } else if (Array.isArray(item)) {
      for (const each of item) stack.push(each);
    } else if (item && typeof item === "object" && !ArrayBuffer.isView(item)) {
      for (const [key, each] of Object.entries(item)) {
        if (key !== "geometry") stack.push(each);
      }
    }
  }
  return [...found.values()];
}

/** The dashboard *fileName* is read on: the one the page carries it for, or
 *  the one whose viewer's run made it. */
function dashboardOf(fileName: string): string | null {
  if (embeddedArtifact(fileName)) return getEmbeddedDashboard()?.meta?.projectId ?? null;
  return dashboardRunProject(fileName) ?? null;
}

/**
 * Note *envelope*, the output *fileName* as the page read it: when the
 * dashboard carries it or a viewer's run made it, the files its rows name
 * are read through the dashboard's links from now on.
 */
export function noteDashboardOutput(fileName: string, envelope: unknown): void {
  const projectId = dashboardOf(fileName);
  if (!projectId) return;
  for (const file of filesNamedIn(envelope)) holders.set(keyOf(file), { projectId, fileName });
}

function fileOf(path: string): MediaFile | null {
  const ref = collectionMediaRef(path);
  return ref ? { datasetId: ref.datasetId, fileId: ref.fileId, kept: ref.kept } : null;
}

/** Whether a dashboard output the page read names the file *path* names. */
export function heldOnADashboard(path: string): boolean {
  const file = fileOf(path);
  return file !== null && holders.has(keyOf(file));
}

/** Ask for the links of everything waiting on one output: one request per
 *  `FILES_PER_ASK` files. A failed ask gives no links, asked again later. */
async function ask(key: string): Promise<void> {
  const batch = waiting.get(key);
  waiting.delete(key);
  if (!batch) return;
  const files = [...batch.files.values()];
  for (let start = 0; start < files.length; start += FILES_PER_ASK) {
    const part = files.slice(start, start + FILES_PER_ASK);
    const askedAt = Date.now();
    let answer: LinksAnswer = {};
    try {
      answer = await apiFetch<LinksAnswer>(
        `/api/projects/${encodeURIComponent(batch.holder.projectId)}/dashboard/media`,
        { method: "POST", body: JSON.stringify({ fileName: batch.holder.fileName, files: part }) },
      );
    } catch {
      answer = {};
    }
    const life = Number.isFinite(answer.expiresIn) ? Number(answer.expiresIn) * 1000 : 0;
    // A file the answer leaves out has no link: asked again once a link would have lapsed.
    const lapsesAt = askedAt + Math.max(life, LINK_LAPSE_MARGIN_MS * 2);
    for (const file of part) links.set(keyOf(file), { url: null, lapsesAt });
    for (const link of answer.links ?? []) {
      if (typeof link?.url === "string") links.set(keyOf(link), { url: link.url, lapsesAt: askedAt + life });
    }
  }
}

/** The file's link, asked for with the other files waiting on its output. */
function linkOf(file: MediaFile, holder: Holder): Promise<Kept | undefined> {
  const key = `${holder.projectId}\n${holder.fileName}`;
  let batch = waiting.get(key);
  if (!batch) {
    const files = new Map<string, MediaFile>();
    // Asked once the cards drawn now have all said what they need.
    const answered = new Promise<void>((resolve) => setTimeout(resolve, 0)).then(() => ask(key));
    batch = { holder, files, answered };
    waiting.set(key, batch);
  }
  batch.files.set(keyOf(file), file);
  return batch.answered.then(() => links.get(keyOf(file)));
}

/**
 * The dashboard's link to the file *path*, a row's media URL, names, as
 * *variant* (the one *path* asks for, else `original`), or null when the
 * dashboard gives none; a promise of it, or null at once for a file no
 * dashboard output the page read names, which is read as on the canvas.
 * *fresh* asks again for one the page holds, as a player does when its link
 * lapsed.
 */
export function dashboardMediaLink(
  path: string,
  { variant, fresh = false }: { variant?: string; fresh?: boolean } = {},
): Promise<DashboardMediaLink | null> | null {
  const ref = collectionMediaRef(path);
  const file = fileOf(path);
  const holder = file ? holders.get(keyOf(file)) : undefined;
  if (!ref || !file || !holder) return null;
  const asked = variant ?? ref.variant ?? "original";
  const withVariant = (kept: Kept | undefined): DashboardMediaLink | null =>
    kept?.url ? { url: `${kept.url}?variant=${encodeURIComponent(asked)}`, lapsesAt: kept.lapsesAt } : null;
  const known = links.get(keyOf(file));
  if (known && !fresh && Date.now() < known.lapsesAt - LINK_LAPSE_MARGIN_MS) {
    return Promise.resolve(withVariant(known));
  }
  return linkOf(file, holder).then(withVariant);
}

/** Forget every output and link: the page went away, or a test starts over. */
export function forgetDashboardMedia(): void {
  holders.clear();
  links.clear();
  waiting.clear();
}
