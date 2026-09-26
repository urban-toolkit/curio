import React from "react";

import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import {
  LAKE_PROVIDER_LABEL,
  unsearchableReason,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { LakeSourceIcon } from "./LakeSourceIcon";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import cardStyles from "./DataLakeSourceCard.module.css";

export interface DataLakeSourceCardProps {
  source: LakeSourceRow;
  selected: boolean;
  onSelect: () => void;
  onBrowse: () => void;
  onViewDetails: () => void;
  /** Right-click. The grid owns the menu; the card reports and selects, which
   *  is what a left-click does too. Same division as the peer pages. */
  onContextMenu?: (e: React.MouseEvent) => void;
}

/**
 * One data portal in the `/catalog/lakes` grid.
 *
 * Structurally identical to `AgentCatalogBrowseCard`, `DataCatalogBrowseCard`
 * and `PackageBrowseCard`, and painted from the same stylesheet: strip header,
 * body, tag row, meta row, actions.
 *
 * The one addition is the source's own mark beside the title, because a portal
 * is a recognisable thing in a way a dataset is not - and it is the fastest way
 * to tell five otherwise similar cards apart. `LakeSourceIcon` falls back to
 * the shared lake glyph in the same box, so a source without one does not
 * shorten the card.
 */
export function DataLakeSourceCard({
  source,
  selected,
  onSelect,
  onBrowse,
  onViewDetails,
  onContextMenu,
}: DataLakeSourceCardProps) {
  const { auth, capabilities } = source;
  const tags = [...source.tags].slice(0, 3);
  const formats = capabilities.formats.map((f) => f.toUpperCase()).join(" · ");

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        selected ? cardStyles.cardActive : "",
        cardStyles.card_lake,
      ]
        .filter(Boolean)
        .join(" ")}
      data-lake-source={source.dirName}
      role="button"
      tabIndex={0}
      onContextMenu={onContextMenu}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${cardStyles.strip_lake}`}>
        <CatalogItemStripHeader
          kind="lake"
          badge={
            <span className={styles.cardFormatBadge}>
              {LAKE_PROVIDER_LABEL[source.provider] ?? source.provider}
            </span>
          }
          trailing={
            capabilities.search ? null : (
              <span className={styles.stripBadgePopular}>Link only</span>
            )
          }
        />
      </div>

      <div className={styles.cardBody}>
        <div className={cardStyles.identity}>
          <LakeSourceIcon iconUrl={source.iconUrl} name={source.name} size="lg" />
          <div className={cardStyles.identityText}>
            <h2 className={`${styles.cardTitle} ${cardStyles.cardTitle}`}>{source.name}</h2>
            <p className={styles.publisher}>{source.publisher || "Unknown publisher"}</p>
          </div>
          {auth.usesToken ? (
            <span
              className={[
                cardStyles.authChip,
                auth.present ? cardStyles.authChipReady : cardStyles.authChipNeeded,
              ].join(" ")}
            >
              {auth.present ? "Token set" : auth.required ? "Token needed" : "Token optional"}
            </span>
          ) : null}
        </div>

        {/* The non-breaking space keeps a description-less card the same height
            as its neighbours, as the peer cards do. */}
        <p
          className={styles.cardDescription}
          {...(!source.description ? { "aria-hidden": true } : {})}
        >
          {source.description || " "}
        </p>

        <div className={styles.tagRow} data-curio-tag-row="true">
          {tags.map((tag) => (
            <span key={tag} className={styles.tag} data-curio-tag-chip="true">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{formats || "No formats declared"}</span>
        <span className={styles.metaRight}>{source.sourceId}</span>
      </div>

      <div className={styles.cardActions}>
        {/* "View details" is the peers' one way in, and opens the same kind of
            modal. Browsing stays on the card as well: it is what this page is
            for, and it writes nothing, unlike the account-level actions the
            peer cards leave to their drawers. It is offered where the drawer
            offers it, and a source that cannot be browsed says why in its
            details instead: a link-only portal, or one missing its token. */}
        <div className={styles.cardActionsLeft} />
        <div className={styles.cardActionsRight}>
          <button
            className={styles.linkButton}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onViewDetails();
            }}
          >
            View details
          </button>
          {unsearchableReason(source) == null ? (
            <button
              className={styles.linkButton}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onBrowse();
              }}
            >
              Browse datasets
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export default DataLakeSourceCard;
