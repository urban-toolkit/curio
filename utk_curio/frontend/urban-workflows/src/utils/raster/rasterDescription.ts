/**
 * What Curio says a raster is where it shows one without drawing it: a chip's
 * hover (components/editing/widgets/ChipPreview, from `readInputPreview`) and
 * a Data Pool's raster tab (adapters/node/components/DataPoolContent). Its size
 * in cells, its bands by their labels and its CRS, read from its envelope: an
 * Autark raster's grid and bands (utils/raster/rasterWire), or, beside a Python
 * raster's file, what the sandbox read of it, which `/get` sends as `meta`: the
 * description the raster route's `X-Curio-Raster` header gives (`RasterMeta`),
 * with each band's label (`rasters.described` in the sandbox).
 *
 * Pure, so it is testable under jest.
 */
import type { RasterMeta } from "./rasterLoad";

/** What is shown of one raster. */
export interface PreviewRaster {
  /** Its size in cells: how many across, then how many down. */
  width: number;
  height: number;
  /** Each band's label, in band order. */
  bands: string[];
  /** Its coordinate system ("EPSG:3395"), when it names one. */
  crs: string | null;
}

/** The bands a description names; it counts the rest. */
export const SHOWN_BANDS = 5;

const isRecord = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value > 0;

const count = (n: number) => n.toLocaleString("en-US");

/** *n* things: "1 band", "7 bands". */
const countOf = (n: number, one: string, many: string) => `${count(n)} ${n === 1 ? one : many}`;

/** A raster *width* by *height* cells, with *bands* labelled, in *crs*; null
 * when its size is not one. */
function rasterSized(width: unknown, height: unknown, bands: string[], crs: unknown): PreviewRaster | null {
  if (!isCount(width) || !isCount(height)) return null;
  return { width, height, bands, crs: typeof crs === "string" && crs ? crs : null };
}

/** A band's label: its own, else `band_<n>`, the id autk-db gives the band at
 * *index* when an Autark node loads the raster. */
const bandLabel = (label: unknown, index: number) =>
  typeof label === "string" && label ? label : `band_${index + 1}`;

/** What is shown of the raster *envelope* holds or describes: an Autark
 * raster's grid and bands' labels, or what the sandbox read of a Python one
 * (`meta`). Null when it says neither, as a reference to a raster does. */
export function rasterOf(envelope: unknown): PreviewRaster | null {
  if (!isRecord(envelope)) return null;
  const data = envelope.data;
  if (isRecord(data) && isRecord(data.grid)) {
    const properties = Array.isArray(data.features) ? data.features[0]?.properties : null;
    const bands: unknown[] = Array.isArray(properties?.bands) ? properties.bands : [];
    const labels = bands.map((band, index) => bandLabel(isRecord(band) ? band.label || band.id : null, index));
    return rasterSized(data.grid.width, data.grid.height, labels, data.grid.crs);
  }
  const meta = envelope.meta as (Partial<RasterMeta> & { bands?: unknown }) | undefined;
  if (isRecord(meta)) {
    const labels: unknown[] = Array.isArray(meta.bands)
      ? meta.bands
      : Array.from({ length: isCount(meta.count) ? meta.count : 0 }, () => null);
    return rasterSized(meta.width, meta.height, labels.map(bandLabel), meta.crs);
  }
  return null;
}

/** A raster's size in cells, its bands and its kind, as a frame's preview
 * gives its rows, its columns and its kind: "40 by 30 cells · 2 bands ·
 * Raster, EPSG:3395". */
export function rasterSizeText(raster: PreviewRaster): string {
  const kind = ["Raster", raster.crs].filter(Boolean).join(", ");
  return `${count(raster.width)} by ${count(raster.height)} cells · ${countOf(raster.bands.length, "band", "bands")} · ${kind}`;
}

/** A raster's first SHOWN_BANDS bands by their labels: "Bands: elevation_m,
 * band_2", "Band: count_tip_parks"; null for a raster of no band. */
export function rasterBandsText(raster: PreviewRaster): string | null {
  const shown = raster.bands.slice(0, SHOWN_BANDS);
  if (shown.length === 0) return null;
  return `${raster.bands.length === 1 ? "Band" : "Bands"}: ${shown.join(", ")}`;
}

/** What `rasterBandsText` leaves out, "first 5 of 7 bands", or null. */
export function rasterCutText(raster: PreviewRaster): string | null {
  return raster.bands.length > SHOWN_BANDS ? `first ${SHOWN_BANDS} of ${count(raster.bands.length)} bands` : null;
}

/** A raster on one line beside its name, as a table's caption gives its size:
 * "raster, 40 by 30 cells, 2 bands", or "raster" when nothing is known of it. */
export function rasterCaption(raster: PreviewRaster | null): string {
  if (!raster) return "raster";
  return `raster, ${count(raster.width)} by ${count(raster.height)} cells, ${countOf(raster.bands.length, "band", "bands")}`;
}
