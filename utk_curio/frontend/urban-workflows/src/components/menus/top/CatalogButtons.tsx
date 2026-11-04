import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

import { CATALOG_KIND_META, type CatalogItemKind } from "../../catalog/CatalogKindVisuals";
import { CATALOG_SECTIONS } from "../../layout/catalogSections";
import headerStyles from "../../layout/GlobalPageHeader.module.css";
import { useNodeCatalogDrawer } from "../../../providers/packages/NodeCatalogDrawerProvider";
import { useAgentCatalogDrawerControls } from "../../../providers/AgentCatalogDrawerProvider";
import { useDatasetCatalogDrawer } from "../../../providers/datasetCatalog";
import { useModelCatalogDrawer } from "../../../providers/modelCatalog";
import { useDiscoveryCatalogDrawer } from "../../../providers/discoveryCatalog";
import { useScenarioCatalogDrawer } from "../../../providers/scenarioCatalog";
import { prefetchDatasetCatalog } from "../../../services/datasetCatalog";
import styles from "./UpMenu.module.css";

/** The catalogs with a drawer, in the order the section pages' bar lists
 *  them, with the glyph each catalog's own page shows. */
export const CANVAS_CATALOGS = CATALOG_SECTIONS.filter((section) => section.onCanvas);

/**
 * The six catalogs, one click each from the canvas bar. They used to sit
 * under a "Data" menu, in another order, and the Discovery Catalog could be
 * reached no other way.
 *
 * Each opens its drawer over the dataflow rather than leaving for the catalog
 * page, so what is picked lands in this dataflow. The visible label is the
 * short name; the accessible name is the catalog's full one, which contains it.
 */
export function CatalogButtons({
  projectId,
}: {
  projectId?: string | null;
}) {
  const { openNodeCatalogDrawer } = useNodeCatalogDrawer();
  const { openAgentCatalogDrawer } = useAgentCatalogDrawerControls();
  const { openDatasetCatalogDrawer } = useDatasetCatalogDrawer();
  const { openModelCatalogDrawer } = useModelCatalogDrawer();
  const { openDiscoveryCatalogDrawer } = useDiscoveryCatalogDrawer();
  const { openScenarioCatalogDrawer } = useScenarioCatalogDrawer();

  const open: Record<CatalogItemKind, (() => void) | undefined> = {
    package: openNodeCatalogDrawer,
    dataset: openDatasetCatalogDrawer,
    agent: openAgentCatalogDrawer,
    source: openDiscoveryCatalogDrawer,
    model: openModelCatalogDrawer,
    scenario: openScenarioCatalogDrawer,
    dataflow: undefined,
    skill: undefined,
  };

  return (
    <div
      className={styles.catalogs}
      role="group"
      aria-label="Catalogs"
    >
      {CANVAS_CATALOGS.map(({ name, shortName, kind }) => (
        <button
          key={kind}
          type="button"
          className={clsx(headerStyles.barButton, styles.catalogButton)}
          aria-label={name}
          data-tooltip={name}
          onClick={() => open[kind]?.()}
          // Warm the Data Catalog's first page while the pointer is on its way.
          onMouseEnter={
            kind === "dataset" && projectId
              ? () => prefetchDatasetCatalog({ dataflowId: projectId, includeHub: true, sort: "recent" })
              : undefined
          }
        >
          <FontAwesomeIcon icon={CATALOG_KIND_META[kind].icon} className={headerStyles.barIcon} />
          <span className={styles.catalogLabel}>{shortName}</span>
        </button>
      ))}
    </div>
  );
}

export default CatalogButtons;
