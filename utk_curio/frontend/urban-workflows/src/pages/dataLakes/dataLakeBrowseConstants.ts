import {
  LAKE_AUTH_LABEL,
  LAKE_PROVIDER_LABEL,
  type LakeAuthMode,
  type LakeProviderType,
} from "../../services/dataLakeCatalog";

/**
 * The filter chips on `/catalog/lakes`, mirroring
 * `pages/dataHub/dataHubBrowseConstants.ts`.
 *
 * Declared rather than derived from the facets so the chip ORDER is stable:
 * a row that reorders itself as counts change is hard to aim at. Facets still
 * drive the counts, and a provider with no sources simply reads zero.
 */
export const PROVIDER_FILTERS: { value: LakeProviderType; label: string }[] = (
  ["socrata", "ckan", "arcgis", "wfs", "direct"] as LakeProviderType[]
).map((value) => ({ value, label: LAKE_PROVIDER_LABEL[value] }));

export const AUTH_FILTERS: { value: LakeAuthMode; label: string }[] = (
  ["public", "optional-token", "required-token"] as LakeAuthMode[]
).map((value) => ({ value, label: LAKE_AUTH_LABEL[value] }));
