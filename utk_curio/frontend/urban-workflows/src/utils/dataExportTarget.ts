/**
 * The name a Data Export node's file downloads under.
 *
 * The node's code writes the file (`curio_export` in the sandbox) and its
 * output is the file's name. A file named in File name, or by code of its own,
 * downloads under that name. A file `curio_export` named by default, File name
 * left empty, takes the name of what feeds the node instead: the input
 * dataset's name, else the feeding node's label, with the file's extension.
 */

/** The stem `curio_export` gives a file when File name is empty. */
export const DEFAULT_STEM = "data_export";

/** Characters a filename cannot carry on Windows, plus the path separators. */
const UNSAFE_FILENAME_CHARS = /[<>:"|?*]/g;
const PATH_SEPARATORS = /[\\/]+/g;
// Escaped rather than written as literal control bytes: the literals made
// git classify this file as binary, so it landed with no reviewable diff and
// stayed invisible to grep and ripgrep.
const CONTROL_CHARS = /[\x00-\x1f\x7f]/g;
/**
 * The extension of a data format at the end of a name: a source titled after
 * its file (`boundaries.geojson`) gives its name without it, so the download
 * ends in its own file's extension once. The sandbox knows the same ones
 * (`DATA_EXTENSIONS`, `sandbox/util/exports.py`).
 */
const DATA_EXTENSION = /\.(csv|tsv|txt|json|geojson|tif|tiff|parquet|gpkg|shp|zip|xlsx|xls|nc|pbf|xml|kml|gml)$/i;

/**
 * Make *name* safe to hand to a browser download.
 *
 * A dataset title is user text and reaches this as a filename, so path
 * separators and the Windows-reserved characters have to go. Returns "" when
 * nothing usable survives, so the caller can fall back rather than offering a
 * file called ``_``.
 */
export function sanitizeExportStem(name: unknown): string {
  if (typeof name !== "string") return "";
  const cleaned = name
    .trim()
    // Path separators first: a title of "../../etc/passwd" must not survive as
    // anything resembling a path.
    .replace(PATH_SEPARATORS, " ")
    .replace(UNSAFE_FILENAME_CHARS, "")
    .replace(CONTROL_CHARS, "")
    // Collapse whitespace so the name is one token.
    .replace(/\s+/g, "_")
    // Leading dots would make a hidden file, or read as a relative path.
    .replace(/^[.\s_]+/, "")
    .replace(/[.\s_]+$/, "");
  // Long titles are common; 80 chars keeps the name recognisable without
  // risking a path-length limit.
  return cleaned.slice(0, 80);
}

/** The name of the file an output names: the text itself, or a path's last part. */
export function exportFileName(value: unknown): string {
  if (typeof value !== "string") return "";
  const parts = value.split(PATH_SEPARATORS);
  return parts[parts.length - 1] ?? "";
}

/**
 * The name the file *file* (the node's output) downloads under. *sourceName*
 * is the best name for what feeds the node when its input names no dataset:
 * the linked dataset's title, else the feeding node's display label.
 */
export function exportDownloadName(
  file: unknown,
  input?: { dataset?: unknown } | null,
  sourceName?: string | null,
): string {
  const name = exportFileName(file);
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  if (stem !== DEFAULT_STEM) return name;
  const extension = dot > 0 ? name.slice(dot) : "";
  const fromDataset =
    typeof input?.dataset === "string"
      ? sanitizeExportStem(input.dataset.replace(/\.[^.]+$/, ""))
      : "";
  const fromSource =
    typeof sourceName === "string" ? sanitizeExportStem(sourceName.trim().replace(DATA_EXTENSION, "")) : "";
  return `${fromDataset || fromSource || DEFAULT_STEM}${extension}`;
}
