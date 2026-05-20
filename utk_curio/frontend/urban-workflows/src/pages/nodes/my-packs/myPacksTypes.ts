import { PackPayload } from "../../../api/packsApi";
import { ForkFamilyGroup } from "../../../utils/forkPackLineage";

/**
 * A single entry in the ordered installed-packs rail.
 * Either a standalone pack or a fork-family group.
 */
export type InstalledHubEntry =
  | { kind: "singleton"; pack: PackPayload }
  | { kind: "family"; family: ForkFamilyGroup<PackPayload> };

/** Shared callback shapes used by all My Packs sub-components. */
export interface MyPacksCallbacks {
  onExport: (pack: PackPayload) => void | Promise<void>;
  onUninstall: (pack: PackPayload) => void | Promise<void>;
  onPaletteDockToggle: (pack: PackPayload) => void | Promise<void>;
  onPublishToCatalog: (dirName: string) => void | Promise<void>;
  onOpenForkInFactory: (pack: PackPayload) => void;
}

