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
  ["socrata", "ckan", "arcgis", "wfs", "direct", "folder", "s3", "huggingface"] as DiscoveryProviderType[]
).map((value) => ({ value, label: DISCOVERY_PROVIDER_LABEL[value] }));

export const AUTH_FILTERS: { value: DiscoveryAuthMode; label: string }[] = (
  ["public", "optional-token", "required-token"] as DiscoveryAuthMode[]
).map((value) => ({ value, label: DISCOVERY_AUTH_LABEL[value] }));
