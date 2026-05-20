import React from "react";
import type { NodeCategory, NodePackMeta } from "../../../registry/types";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../constants/nodeCategoryShortLabels";
import { formatForkOfSubtitle } from "../../../utils/forkPackLineage";
import styles from "./PackMetaHeader.module.css";

export interface PackMetaHeaderProps {
  /** Pack-level metadata from the node descriptor. */
  pack: NodePackMeta;
  /** Category of the node kind (used for the badge label). */
  category: NodeCategory;
  /**
   * When `true` (a suggestion node is active), pointer events are suppressed
   * so the header cannot be interacted with.
   */
  suggestionActive: boolean;
}

/**
 * Renders the pack provenance strip shown at the top of a canvas node whose
 * descriptor originates from an installed pack.
 *
 * Displays a category badge, the `packId@major` monospace tag, and — when the
 * pack declares a fork lineage — a small "fork of …" subtitle.
 */
export function PackMetaHeader({ pack, category, suggestionActive }: PackMetaHeaderProps) {
  const forkSubtitle = pack.lineage != null ? formatForkOfSubtitle(pack.lineage) : null;

  return (
    <div
      className={styles.root}
      style={suggestionActive ? { pointerEvents: "none" } : undefined}
    >
      <div className={styles.row}>
        <span className={styles.categoryBadge}>
          {NODE_CATEGORY_SHORT_LABEL[category]}
        </span>
        <span
          className={styles.packId}
          title={`${pack.packId}@${pack.major}`}
        >
          {pack.packId}@{pack.major}
        </span>
      </div>

      {forkSubtitle ? (
        <span className={styles.forkSubtitle} title={forkSubtitle.title}>
          {forkSubtitle.text}
        </span>
      ) : null}
    </div>
  );
}

