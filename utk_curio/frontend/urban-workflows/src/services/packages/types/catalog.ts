/**
 * The catalog surfaces' shapes: families and collisions, the factory capabilities, and the drawer's sort/tab vocabulary.
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

export interface CatalogFamilyPayload {
  familyKey: string;
  dirNames: string[];
}

export interface CatalogCollisionPayload {
  familyKey: string;
  channel: string;
  version: string;
  dirNames: string[];
}

export interface FactoryCapabilities {
  catalogPublish: boolean;
}

/** Which tab the Node Catalog drawer shows. */
export type DrawerTab = "browse" | "installed";

/** Row ordering shared by the drawer, the browse page and the agents catalog (memo dev/143 rule 4). */
export type SortMode = "new" | "name";
