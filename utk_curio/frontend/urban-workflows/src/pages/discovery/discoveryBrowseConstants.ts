import {
  DISCOVERY_AUTH_LABEL,
  DISCOVERY_PROVIDER_LABEL,
  type DiscoveryAuthMode,
  type DiscoveryProviderType,
} from "../../services/discoveryCatalog";

/**
 * The filter chips on `/catalog/discovery`, mirroring
 * `pages/dataCatalog/dataCatalogBrowseConstants.ts`.
 *
 * Declared rather than derived from the facets so the chip ORDER is stable:
 * a row that reorders itself as counts change is hard to aim at. Facets still
 * drive the counts, and a provider with no sources simply reads zero.
 */
export const PROVIDER_FILTERS: { value: DiscoveryProviderType; label: string }[] = (
  [
    "socrata", "ckan", "arcgis", "wfs", "direct", "folder", "s3", "huggingface",
    "autark-osm", "mapillary", "google-streetview", "overture", "huggingface-models",
  ] as DiscoveryProviderType[]
).map((value) => ({ value, label: DISCOVERY_PROVIDER_LABEL[value] }));

export type DiscoverySortMode = "name" | "provider";

/** The sort the page's select and the canvas drawer's search row offer. */
export const DISCOVERY_SORT_OPTIONS: { value: DiscoverySortMode; label: string }[] = [
  { value: "name", label: "Sort: Name" },
  { value: "provider", label: "Sort: Provider" },
];

export const AUTH_FILTERS: { value: DiscoveryAuthMode; label: string }[] = (
  ["public", "optional-token", "required-token"] as DiscoveryAuthMode[]
).map((value) => ({ value, label: DISCOVERY_AUTH_LABEL[value] }));
