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
import styles from "../catalog/CatalogBrowseLayout.module.css";

export interface DataLakeCatalogBrowseDrawerProps {
  source: LakeSourceRow | null;
  onBrowse: (source: LakeSourceRow) => void;
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
  onClose,
  onLayoutChange,
}: DataLakeCatalogBrowseDrawerProps) {
  return (
    <CatalogBrowseDrawerShell presented={source != null} onLayoutChange={onLayoutChange}>
      {source ? (
        <DataLakeDrawerContent source={source} onBrowse={onBrowse} onClose={onClose} />
      ) : null}
    </CatalogBrowseDrawerShell>
  );
}

function bytesLabel(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${Math.round(mb)} MB` : `${Math.round(bytes / 1024)} KB`;
}

const DataLakeDrawerContent: React.FC<{
  source: LakeSourceRow;
  onBrowse: (source: LakeSourceRow) => void;
  onClose: () => void;
}> = ({ source, onBrowse, onClose }) => {
  const { auth, capabilities } = source;
  const blocked = unsearchableReason(source);

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
      infoRows={[
        { label: "Provider", value: LAKE_PROVIDER_LABEL[source.provider] ?? source.provider },
        source.baseUrl ? { label: "Endpoint", value: source.baseUrl } : null,
        source.homepage
          ? {
              label: "Homepage",
              value: (
                <a href={source.homepage} target="_blank" rel="noreferrer noopener">
                  {new URL(source.homepage).host}
                </a>
              ),
            }
          : null,
        source.license ? { label: "Licence", value: source.license } : null,
        { label: "Search", value: capabilities.search ? "Yes" : "Link only" },
        {
          label: "Formats",
          value: capabilities.formats.map((f) => f.toUpperCase()).join(", ") || "None",
        },
        { label: "Max download", value: bytesLabel(capabilities.maxDownloadBytes) },
      ]}
      tags={source.tags}
      sections={
        auth.usesToken ? (
          <CatalogDrawerSection label="Access">
            <CatalogDrawerList
              items={[
                <li key="mode">
                  {auth.required
                    ? "This portal will not answer without a token."
                    : "Works without a token; one raises the rate limit."}
                </li>,
                <li key="slot">
                  Credential: <code>{auth.secretId}</code>
                  {auth.present ? " (set on your account)" : " (not set)"}
                </li>,
                auth.helpUrl ? (
                  <li key="help">
                    <a href={auth.helpUrl} target="_blank" rel="noreferrer noopener">
                      How to get one
                    </a>
                  </li>
                ) : null,
              ].filter(Boolean) as React.ReactNode[]}
            />
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
    />
  );
};

export default DataLakeCatalogBrowseDrawer;
