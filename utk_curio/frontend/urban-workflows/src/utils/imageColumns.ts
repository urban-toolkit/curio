/**
 * Which columns of a frame hold images, and how to turn one cell into an
 * <img> source.
 *
 * Simple View used to answer the first question with `input.data.image_id`,
 * which is a DataFrame *column map* - so a GeoDataFrame, whose columns live at
 * `data.features[i].properties`, could never reach image mode, and a column of
 * image URLs had no path at all. Three separate docs described three different
 * rules (see `docs/ARCHITECTURE.md` and the note in `simpleVisBehavior`); this
 * module is the one rule they now all point at.
 *
 * The rule, in order:
 *
 *   1. If any RECOGNIZED_COLUMNS name is present and holds image-like values,
 *      those are the image columns and nothing else is considered.
 *   2. Otherwise sniff every column's values.
 *
 * Bare base64 is only honoured in step 1. A column of long hex ids passes any
 * base64 charset test, so sniffing for it would turn ordinary id columns into
 * broken image grids; a caller who really has base64 names the column.
 * Likewise step 2 requires a recognisable image extension on http(s) URLs,
 * while step 1 does not - Street View's `image_url` is a query-string API call
 * with no extension, and it reaches us under a recognized name.
 *
 * Pure and React-free so it can be tested directly.
 */

export type FrameRow = Record<string, unknown>;

/** Names checked first, in this order. */
export const RECOGNIZED_COLUMNS: readonly string[] = [
  'image_content',
  'image_url',
  'image',
  'thumbnail',
  'overlay_url',
];

/** Fraction of a column's non-null cells that must look like images. */
const MATCH_THRESHOLD = 0.6;

/** Long enough that ordinary words and short ids cannot qualify. */
const MIN_BASE64_LENGTH = 64;

const BASE64_RE = /^[A-Za-z0-9+/\s]+={0,2}$/;
const IMAGE_EXTENSION_RE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)(\?|#|$)/i;

/**
 * How a single cell can become an `<img>` source.
 *
 * `authed` is the interesting one: a same-origin `/api/...` path is served by
 * Curio's own backend, which resolves WHICH user is asking from the bearer
 * token. A bare `<img src>` cannot send that header, so those have to be
 * fetched and handed to the DOM as an object URL instead.
 */
export type ImageSource =
  | { kind: 'direct'; src: string }
  | { kind: 'authed'; path: string };

function isBareBase64(value: string): boolean {
  return value.length >= MIN_BASE64_LENGTH && BASE64_RE.test(value);
}

/**
 * Resolve one cell, or null when it is not an image.
 *
 * `allowBase64` is false while sniffing unnamed columns; see the module note.
 */
export function resolveImageSource(
  value: unknown,
  { allowBase64 = true, requireExtension = false } = {},
): ImageSource | null {
  if (typeof value !== 'string') return null;
  const raw = value.trim();
  if (!raw) return null;

  if (raw.startsWith('data:image/')) return { kind: 'direct', src: raw };
  if (raw.startsWith('/api/')) return { kind: 'authed', path: raw };
  if (/^https?:\/\//i.test(raw)) {
    if (requireExtension && !IMAGE_EXTENSION_RE.test(raw)) return null;
    return { kind: 'direct', src: raw };
  }
  if (allowBase64 && isBareBase64(raw)) {
    // The historical `image_content` contract: raw PNG bytes, no data: prefix.
    return { kind: 'direct', src: `data:image/png;base64,${raw}` };
  }
  return null;
}

function columnHoldsImages(
  rows: readonly FrameRow[],
  column: string,
  opts: { allowBase64: boolean; requireExtension: boolean },
): boolean {
  let present = 0;
  let matched = 0;
  for (const row of rows) {
    const value = row?.[column];
    if (value == null || value === '') continue;
    present += 1;
    if (resolveImageSource(value, opts)) matched += 1;
  }
  if (present === 0) return false;
  return matched / present >= MATCH_THRESHOLD;
}

/** Column names of *rows*, taken from the union so a holey frame still works. */
function columnsOf(rows: readonly FrameRow[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    if (row && typeof row === 'object') {
      for (const key of Object.keys(row)) seen.add(key);
    }
  }
  return Array.from(seen);
}

/**
 * The image columns of *rows*, in display order. Empty means "render a table",
 * which is exactly what Simple View did before this existed.
 */
export function resolveImageColumns(rows: readonly FrameRow[]): string[] {
  if (!Array.isArray(rows) || rows.length === 0) return [];
  const columns = columnsOf(rows);

  const recognized = RECOGNIZED_COLUMNS.filter(
    (name) =>
      columns.includes(name) &&
      columnHoldsImages(rows, name, { allowBase64: true, requireExtension: false }),
  );
  if (recognized.length > 0) return recognized;

  return columns.filter((name) =>
    columnHoldsImages(rows, name, { allowBase64: false, requireExtension: true }),
  );
}
