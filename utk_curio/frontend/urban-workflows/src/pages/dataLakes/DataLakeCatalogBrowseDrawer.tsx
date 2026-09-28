import React from "react";

import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import {
  CatalogBrowseDrawerBody,
  CatalogDrawerList,
  CatalogDrawerSection,
} from "../catalog/CatalogBrowseDrawerBody";
import {
  LAKE_AUTH_LABEL,
  LAKE_PROVIDER_LABEL,
  unsearchableReason,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { LakeSourceIcon } from "./LakeSourceIcon";
import { lakeSourceAccessItems, lakeSourceInfoRows } from "./lakeSourceFacts";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataLakeCatalogBrowseDrawerProps {
  source: LakeSourceRow | null;
  onBrowse: (source: LakeSourceRow) => void;
  onViewDetails: (source: LakeSourceRow) => void;
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

/**
 * The right-hand detail drawer on `/catalog/lakes`.
 *
 * Composed from `CatalogBrowseDrawerBody` like the other three, which is the
 * point: those drawers drifted apart when each page assembled its own markup,
 * and `catalogDrawerParity.test.ts` exists so a fourth cannot start the same
 * way. Everything here is content decisions - which info rows, which action -
 * and no layout of its own.
 */
export function DataLakeCatalogBrowseDrawer({
  source,
  onBrowse,
  onViewDetails,
  onClose,
  onLayoutChange,
}: DataLakeCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={source != null} onLayoutChange={onLayoutChange}>
      {source ? (
        <DataLakeDrawerContent
          source={source}
          onBrowse={onBrowse}
          onViewDetails={onViewDetails}
          onClose={onClose}
        />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

const DataLakeDrawerContent: React.FC<{
  source: LakeSourceRow;
  onBrowse: (source: LakeSourceRow) => void;
  onViewDetails: (source: LakeSourceRow) => void;
  onClose: () => void;
}> = ({ source, onBrowse, onViewDetails, onClose }) => {
  const { auth } = source;
  const blocked = unsearchableReason(source);
  const access = lakeSourceAccessItems(source);

  return (
    <CatalogBrowseDrawerBody
      kind="lake"
      headerTitle="Data lake details"
      onClose={onClose}
      hero={
        <div className={styles.drawerKindHero}>
          <LakeSourceIcon iconUrl={source.iconUrl} name={source.name} size="lg" />
        </div>
      }
      title={source.name}
      badges={
        <>
          <span className={styles.drawerCategoryBadge}>
            {LAKE_PROVIDER_LABEL[source.provider] ?? source.provider}
          </span>
          {auth.usesToken && auth.present ? (
            <span className={styles.drawerInstalledBadge}>Token set</span>
          ) : null}
        </>
      }
      subtitle={
        <span className={styles.drawerPublisherText}>
          {source.publisher || "Unknown publisher"}
        </span>
      }
      metaLeft={LAKE_AUTH_LABEL[auth.mode] ?? auth.mode}
      metaRight={source.sourceId}
      /* A source roster changes when an operator edits it, which is rare and
         not a freshness signal a user can act on, so the dot stays grey rather
         than implying we know how current the portal's own data is. */
      fresh={false}
      description={source.description}
      infoLabel="Source"
      infoRows={lakeSourceInfoRows(source)}
      tags={source.tags}
      sections={
        access.length > 0 ? (
          <CatalogDrawerSection label="Access">
            <CatalogDrawerList items={access} />
          </CatalogDrawerSection>
        ) : null
      }
      primaryAction={
        blocked ? (
          <p className={styles.drawerNote}>{blocked}</p>
        ) : (
          <button
            type="button"
            className={styles.addToPaletteBtn}
            onClick={() => onBrowse(source)}
          >
            Browse datasets
          </button>
        )
      }
      secondaryAction={
        /* The way out of the panel, as on the other three drawers: the same
           details modal the card's "View details" opens. */
        <button
          className={styles.drawerLinkButton}
          type="button"
          onClick={() => onViewDetails(source)}
        >
          View details
        </button>
      }
    />
  );
};

export default DataLakeCatalogBrowseDrawer;
