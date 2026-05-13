import { v4 as uuid } from "uuid";
import { AccessLevelType, NodeType } from "../constants";

// ── Shared scale ───────────────────────────────────────────────────────
// CITYSCAPES_CLASSES + CITYSCAPES_COLORS are reused across all three Vega-Lite
// templates so map polygons, point markers, and bar segments stay visually
// consistent (a building region looks the same green everywhere).
const CITYSCAPES_CLASSES = [
  "road", "sidewalk", "building", "vegetation",
  "wall", "fence", "pole", "traffic sign",
];
const CITYSCAPES_COLORS = [
  "#4A90D9", "#8B5CF6", "#2ECC71", "#F5A623",
  "#95A5A6", "#BDC3C7", "#E74C3C", "#E67E22",
];

// Chicago neighborhoods basemap is served by the FastAPI backend.
// We hit it via the Curio Flask proxy so the URL is same-origin from the
// Curio frontend and CORS is not in play.
const CHICAGO_NEIGHBORHOODS_URL =
  "http://localhost:5002/api/streetvision/data/basemap/chicago_neighborhoods.geojson";

const SHARED_FONTS = "Inter, system-ui, sans-serif";

// ── Helpers shared by every template ───────────────────────────────────
const titleBlock = (text: string, subtitle: string) => ({
  text,
  subtitle,
  anchor: "start",
  fontSize: 22,
  fontWeight: 700,
  subtitleFontSize: 13,
  subtitleColor: "#64748b",
  subtitlePadding: 6,
  color: "#0f172a",
  offset: 14,
});

// Point tooltip used in both standalone Map View and the Linked Map+Bars view.
// Includes neighborhood + a breakdown of the four most-common classes (per
// Priority 3). The id is truncated for display; the full one is in the data.
const POINT_TOOLTIP = [
  { field: "id_short", type: "nominal", title: "Image" },
  { field: "neighborhood_name", type: "nominal", title: "Neighborhood" },
  { field: "latitude", type: "quantitative", format: ".5f", title: "Lat" },
  { field: "longitude", type: "quantitative", format: ".5f", title: "Lon" },
  { field: "dominant_class", type: "nominal", title: "Top class" },
  { field: "dominant_pct", type: "quantitative", format: ".1f", title: "Top %" },
  { field: "road", type: "quantitative", format: ".1f", title: "Road %" },
  { field: "building", type: "quantitative", format: ".1f", title: "Building %" },
  { field: "sidewalk", type: "quantitative", format: ".1f", title: "Sidewalk %" },
  { field: "vegetation", type: "quantitative", format: ".1f", title: "Veg %" },
];

// Polygon tooltip — only the basemap layer uses this. Pulls the per-neighborhood
// aggregates that the backend's /enrich_with_neighborhoods endpoint joined onto
// each point and that we then `lookup` back from the basemap.
const POLYGON_TOOLTIP = [
  { field: "properties.name", type: "nominal", title: "Neighborhood" },
  { field: "nbhd_image_count", type: "quantitative", title: "Images" },
  { field: "nbhd_dominant_class", type: "nominal", title: "Dominant" },
  { field: "nbhd_dominant_pct", type: "quantitative", format: ".1f", title: "Dominant %" },
];

// ── Layer 1: analytic basemap (Chicago neighborhoods, lookup-joined) ───
// The lookup pulls per-neighborhood aggregates from the *points* dataset
// (already enriched by the backend so every point in a given neighborhood
// carries the same nbhd_* fields). Polygons containing no points stay
// flat slate; polygons with data get colored by the dominant class and
// shaded by its percentage.
const polygonLayer = (pointsDataName = "data") => ({
  data: {
    url: CHICAGO_NEIGHBORHOODS_URL,
    format: { type: "json", property: "features" },
  },
  transform: [
    {
      lookup: "properties.name",
      from: {
        data: { name: pointsDataName },
        key: "neighborhood_name",
        fields: ["nbhd_dominant_class", "nbhd_dominant_pct", "nbhd_image_count"],
      },
    },
  ],
  // Visible-but-neutral B&W base: every Chicago neighborhood polygon renders
  // with a faint slate fill and a darker slate stroke so the whole city
  // footprint is readable, then searched neighborhoods overlay in vivid
  // Cityscapes colors. Slate-200 (`#e2e8f0`) is light enough to keep the
  // colored blocks dominant, but dark enough that every other neighborhood
  // is still clearly drawn against the white chart background — earlier
  // tries with slate-100 / pure-white made un-matched polygons invisible
  // and the projection's auto-fit made the whole map look truncated.
  mark: { type: "geoshape", stroke: "#475569", strokeWidth: 0.6 },
  encoding: {
    fill: {
      condition: {
        test: "datum.nbhd_dominant_class != null",
        field: "nbhd_dominant_class",
        type: "nominal",
        scale: { domain: CITYSCAPES_CLASSES, range: CITYSCAPES_COLORS },
        legend: null,
      },
      // Slate-200 — visible against the white chart background but neutral
      // enough that the colored blocks remain the obvious focal point.
      value: "#e2e8f0",
    },
    fillOpacity: {
      condition: {
        test: "datum.nbhd_dominant_class != null",
        field: "nbhd_dominant_pct",
        type: "quantitative",
        // Floor 0.55 so colored blocks read as solid Cityscapes color
        // rather than washed-out tints.
        scale: { domain: [0, 100], range: [0.55, 0.95] },
        legend: null,
      },
      value: 1,
    },
    tooltip: POLYGON_TOOLTIP,
  },
});

// ── Layer 1b: neighborhood-name labels on highlighted polygons ─────────
// Only labels polygons that survived the lookup (i.e., neighborhoods that
// contain at least one queried point). Centroids are precomputed by the
// backend (/data/basemap/chicago_neighborhoods.geojson injects
// `properties.centroid_lon` / `properties.centroid_lat` into every feature
// using shapely), so we don't depend on Vega's `geoCentroid` expression —
// which is brittle across Vega-Lite versions and quietly broke before.
// White stroke + paintOrder: "stroke" gives a halo so labels stay legible
// over saturated Cityscapes fills.
const labelLayer = (pointsDataName = "data") => ({
  data: {
    url: CHICAGO_NEIGHBORHOODS_URL,
    format: { type: "json", property: "features" },
  },
  transform: [
    {
      lookup: "properties.name",
      from: {
        data: { name: pointsDataName },
        key: "neighborhood_name",
        fields: ["nbhd_dominant_class"],
      },
    },
    // Two guards: (1) only label matched neighborhoods, (2) only render
    // labels when the basemap features actually carry centroids — older
    // backend builds served the GeoJSON without centroid_lon / centroid_lat
    // injected, and feeding null longitudes into the projection produced
    // NaN coordinates that broke the entire layered chart (polygons + points
    // would silently disappear). With this filter, the label layer becomes
    // a no-op on stale backends instead of taking the rest of the chart
    // down with it.
    {
      filter:
        "datum.nbhd_dominant_class != null && datum.properties != null && datum.properties.centroid_lon != null && datum.properties.centroid_lat != null",
    },
  ],
  mark: {
    type: "text",
    fontSize: 12,
    fontWeight: 700,
    color: "#0f172a",
    stroke: "#ffffff",
    strokeWidth: 3.5,
    paintOrder: "stroke",
    dy: -1,
  },
  encoding: {
    longitude: { field: "properties.centroid_lon", type: "quantitative" },
    latitude: { field: "properties.centroid_lat", type: "quantitative" },
    text: { field: "properties.name", type: "nominal" },
  },
});

// ── Layer 2: Street Vision points (with optional selection-aware opacity) ──
const pointLayer = (selectionParam?: string) => ({
  transform: [
    { calculate: "substring(datum.image_id, 0, 6) + '…'", as: "id_short" },
  ],
  mark: { type: "circle", stroke: "#ffffff", strokeWidth: 1.5 },
  encoding: {
    longitude: { field: "longitude", type: "quantitative" },
    latitude: { field: "latitude", type: "quantitative" },
    size: {
      field: "dominant_pct",
      type: "quantitative",
      scale: { range: [80, 320] },
      legend: null,
    },
    color: {
      field: "dominant_class",
      type: "nominal",
      scale: { domain: CITYSCAPES_CLASSES, range: CITYSCAPES_COLORS },
      legend: {
        title: "Dominant class",
        titleFontSize: 12,
        titleColor: "#475569",
        orient: "right",
        symbolType: "circle",
        symbolSize: 120,
        labelFontSize: 12,
        labelColor: "#334155",
        offset: 14,
        rowPadding: 4,
      },
    },
    ...(selectionParam
      ? {
          opacity: {
            condition: { param: selectionParam, value: 0.95, empty: true },
            value: 0.18,
          },
          strokeWidth: {
            condition: { param: selectionParam, value: 2.5, empty: false },
            value: 1.5,
          },
        }
      : { opacity: { value: 0.92 } }),
    tooltip: POINT_TOOLTIP,
  },
});

const SHARED_CONFIG = {
  view: { stroke: null },
  axis: { labelFont: SHARED_FONTS, titleFont: SHARED_FONTS },
  legend: { labelFont: SHARED_FONTS, titleFont: SHARED_FONTS },
  title: { font: SHARED_FONTS, subtitleFont: SHARED_FONTS },
};

// ══════════════════════════════════════════════════════════════════════
// TEMPLATE 1 — Map View (only template; analytic polygons + auto-fit)
// ══════════════════════════════════════════════════════════════════════
//
// Mercator projection without explicit scale/center means Vega-Lite
// auto-fits to the union of all geo data — and since the basemap covers
// every Chicago neighborhood, the full city footprint is always visible
// regardless of where the user's queried points fall. Searched
// neighborhoods light up in their dominant Cityscapes color; the rest of
// Chicago stays as faint slate outlines so the city silhouette reads
// clearly.
const STREET_VISION_MAP_VIEW = {
  $schema: "https://vega.github.io/schema/vega-lite/v5.json",
  title: titleBlock(
    "Street Vision — Map View",
    "Polygons: dominant class per neighborhood · Points: per-image dominant class & %",
  ),
  background: "#ffffff",
  padding: { left: 16, right: 16, top: 10, bottom: 10 },
  projection: { type: "mercator" },
  layer: [polygonLayer("data"), labelLayer("data"), pointLayer()],
  config: SHARED_CONFIG,
};

// ══════════════════════════════════════════════════════════════════════
// TEMPLATE 2 — Neighborhood Summary (high-volume bar alternative)
// ══════════════════════════════════════════════════════════════════════
//
// At 100+ images, the per-image stacked bar (vegaLifecycle DEFAULT_SPEC)
// becomes unreadable — bars are 4 px wide and X labels overlap. This
// template trades per-image granularity for spatial roll-up: one
// horizontal bar per neighborhood, length = images sampled, color =
// dominant Cityscapes class. Scales cleanly to any sample size because
// Chicago has only ~98 neighborhoods total.
//
// Aggregation works because the backend's enrich_with_neighborhoods
// endpoint stamps every point in a neighborhood with the SAME
// `nbhd_dominant_class` / `nbhd_dominant_pct` values — so taking
// `min` of those constant fields after a `groupby: neighborhood_name`
// trivially recovers the per-neighborhood value.
const STREET_VISION_NBHD_SUMMARY = {
  $schema: "https://vega.github.io/schema/vega-lite/v5.json",
  title: titleBlock(
    "Street Vision — Neighborhood Summary",
    "Per-neighborhood image counts, colored by dominant Cityscapes class",
  ),
  background: "#ffffff",
  padding: { left: 16, right: 16, top: 10, bottom: 14 },
  transform: [
    { filter: "datum.neighborhood_name != null" },
    {
      aggregate: [
        { op: "count", as: "image_count" },
        { op: "min", field: "nbhd_dominant_class", as: "dominant_class" },
        { op: "min", field: "nbhd_dominant_pct", as: "dominant_pct" },
      ],
      groupby: ["neighborhood_name"],
    },
  ],
  mark: {
    type: "bar",
    cornerRadiusEnd: 6,
    stroke: "#ffffff",
    strokeWidth: 1.5,
  },
  encoding: {
    y: {
      field: "neighborhood_name",
      type: "nominal",
      sort: { op: "max", field: "image_count", order: "descending" },
      axis: {
        title: null,
        labelFontSize: 12,
        labelColor: "#334155",
        domainOpacity: 0,
        tickOpacity: 0,
        labelPadding: 8,
      },
    },
    x: {
      field: "image_count",
      type: "quantitative",
      axis: {
        title: "Images sampled",
        titleFontSize: 12,
        titleColor: "#475569",
        titleFontWeight: 500,
        titlePadding: 10,
        labelFontSize: 11,
        labelColor: "#94a3b8",
        gridColor: "#f1f5f9",
        domainOpacity: 0,
        tickOpacity: 0,
        format: "d",
      },
    },
    color: {
      field: "dominant_class",
      type: "nominal",
      scale: { domain: CITYSCAPES_CLASSES, range: CITYSCAPES_COLORS },
      legend: {
        title: "Dominant class",
        titleFontSize: 12,
        titleColor: "#475569",
        orient: "right",
        symbolType: "circle",
        symbolSize: 120,
        labelFontSize: 12,
        labelColor: "#334155",
        offset: 14,
        rowPadding: 4,
      },
    },
    tooltip: [
      { field: "neighborhood_name", type: "nominal", title: "Neighborhood" },
      { field: "image_count", type: "quantitative", title: "Images" },
      { field: "dominant_class", type: "nominal", title: "Dominant class" },
      { field: "dominant_pct", type: "quantitative", format: ".1f", title: "Dominant %" },
    ],
  },
  config: SHARED_CONFIG,
};

// ══════════════════════════════════════════════════════════════════════
// Built-in template registry
// ══════════════════════════════════════════════════════════════════════
//
// We previously shipped a third "Linked Map + Bars" template using
// `vconcat` with a shared point selection, but Vega-Lite has a known bug
// (`Duplicate signal name: <selectionName>_tuple`) when a point selection
// is referenced in multiple children of a vconcat. We rolled it back —
// the standalone bar chart (vegaLifecycle DEFAULT_SPEC) and standalone
// Map View below already cover the use cases cleanly.
const BUILT_IN_TEMPLATES = [
  {
    id: uuid(),
    type: NodeType.VIS_VEGA,
    name: "Street Vision — Map View",
    description:
      "Mercator map of all Chicago neighborhoods. Searched neighborhoods " +
      "color-coded by dominant Cityscapes class; per-image points overlaid. " +
      "Connect to CV Analysis output.",
    accessLevel: AccessLevelType.ANY,
    code: JSON.stringify(STREET_VISION_MAP_VIEW, null, 2),
    custom: false,
  },
  {
    id: uuid(),
    type: NodeType.VIS_VEGA,
    name: "Street Vision — Neighborhood Summary",
    description:
      "Horizontal bars: one per Chicago neighborhood, length = images " +
      "sampled, color = dominant Cityscapes class. Use this instead of " +
      "the per-image stacked bar when sample size is large (50+ images).",
    accessLevel: AccessLevelType.ANY,
    code: JSON.stringify(STREET_VISION_NBHD_SUMMARY, null, 2),
    custom: false,
  },
];

export default async function useTemplates() {
  let serverTemplates: any[] = [];
  try {
    const response = await fetch(process.env.BACKEND_URL + '/templates');
    if (response.ok) {
      serverTemplates = await response.json();
    }
  } catch (error) {
    console.error('Failed to fetch templates:', error);
  }
  // Always include built-in templates so the Map View is available even if
  // the backend has no stored templates.
  return [...BUILT_IN_TEMPLATES, ...serverTemplates];
}
