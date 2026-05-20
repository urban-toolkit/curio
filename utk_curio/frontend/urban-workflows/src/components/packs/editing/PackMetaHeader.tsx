import React, { useCallback, useMemo } from "react";
import type { NodeCategory, NodePackMeta } from "../../../registry/types";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../constants/nodeCategoryShortLabels";
import { formatForkOfSubtitle } from "../../../utils/forkPackLineage";
import { usePackPalette } from "../../../providers/PackPaletteContext";
import { useHeaderIconDragClick } from "../../../utils/headerIconDragClick";
import styles from "./PackMetaHeader.module.css";

export interface PackMetaHeaderProps {
  pack: NodePackMeta;
  category: NodeCategory;
  suggestionActive: boolean;
}

/**
 * Category + PACK pills for the canvas node title bar (right of the kind label).
 * PACK shows `packId@major` in a tooltip and focuses that pack in the left palette.
 */
export function PackMetaHeader({ pack, category, suggestionActive }: PackMetaHeaderProps) {
  const { setActivePackKey, setPaletteDockRevealCoord } = usePackPalette();
  const coord = `${pack.packId}@${pack.major}`;

  const packTooltip = useMemo(() => {
    const lines = [coord];
    if (pack.lineage != null) {
      const fork = formatForkOfSubtitle(pack.lineage);
      lines.push(fork.text);
      if (fork.title) lines.push(fork.title);
    }
    lines.push("Click to open this pack in the Packs palette");
    return lines.join("\n");
  }, [coord, pack.lineage]);

  const focusPackInPalette = useCallback(() => {
    if (suggestionActive) return;
    setActivePackKey(coord);
    setPaletteDockRevealCoord(coord);
  }, [coord, setActivePackKey, setPaletteDockRevealCoord, suggestionActive]);

  const packBadgeClick = useHeaderIconDragClick(focusPackInPalette);

  return (
    <div
      className={styles.pills}
      style={suggestionActive ? { pointerEvents: "none" } : undefined}
    >
      <span className={styles.categoryBadge} title={NODE_CATEGORY_SHORT_LABEL[category]}>
        {NODE_CATEGORY_SHORT_LABEL[category]}
      </span>
      <button
        type="button"
        className={styles.packBadge}
        title={packTooltip}
        aria-label={`Open pack ${coord} in Packs palette`}
        {...packBadgeClick}
      >
        PACK
      </button>
    </div>
  );
}
