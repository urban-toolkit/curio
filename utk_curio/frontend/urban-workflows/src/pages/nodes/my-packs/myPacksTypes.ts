import { PackPayload } from "../../../api/packsApi";
import { InstalledPackWarehouseRow } from "../../../utils/forkPackLineage";

/** Ordered installed-packs rail row (singleton or fork-family accordion). */
export type InstalledHubEntry = InstalledPackWarehouseRow<PackPayload>;

/** Shared callback shapes used by all My Packs sub-components. */
export interface MyPacksCallbacks {
  onExport: (pack: PackPayload) => void | Promise<void>;
  onUninstall: (pack: PackPayload) => void | Promise<void>;
  onPaletteDockToggle: (pack: PackPayload) => void | Promise<void>;
  onPublishToCatalog: (dirName: string) => void | Promise<void>;
  onOpenForkInFactory: (pack: PackPayload) => void;
}
