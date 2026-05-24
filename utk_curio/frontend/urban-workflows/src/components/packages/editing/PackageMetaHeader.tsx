import React, { useCallback, useMemo } from "react";
import type { NodeCategory, NodePackageMeta } from "../../../registry/types";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../constants/nodeCategoryShortLabels";
import { formatForkOfSubtitle } from "../../../utils/forkPackageLineage";
import { usePackagePalette } from "../../../providers/PackagePaletteContext";
import { useHeaderIconDragClick } from "../../../utils/headerIconDragClick";
import styles from "./PackageMetaHeader.module.css";

export interface PackageMetaHeaderProps {
  package: NodePackageMeta;
  category: NodeCategory;
  suggestionActive: boolean;
}

/**
 * Category + PACKAGE pills for the canvas node title bar (right of the kind label).
 * PACKAGE shows `packageId@major` in a tooltip and focuses that package in the left palette.
 */
export function PackageMetaHeader({ package, category, suggestionActive }: PackageMetaHeaderProps) {
  const { setActivePackageKey, setPaletteDockRevealCoord } = usePackagePalette();
  const coord = `${package.packageId}@${package.major}`;

  const packageTooltip = useMemo(() => {
    const lines = [coord];
    if (package.lineage != null) {
      const fork = formatForkOfSubtitle(package.lineage);
      lines.push(fork.text);
      if (fork.title) lines.push(fork.title);
    }
    lines.push("Click to open this package in the Packages palette");
    return lines.join("\n");
  }, [coord, package.lineage]);

  const focusPackageInPalette = useCallback(() => {
    if (suggestionActive) return;
    setActivePackageKey(coord);
    setPaletteDockRevealCoord(coord);
  }, [coord, setActivePackageKey, setPaletteDockRevealCoord, suggestionActive]);

  const packageBadgeClick = useHeaderIconDragClick(focusPackageInPalette);

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
        className={styles.packageBadge}
        title={packageTooltip}
        aria-label={`Open package ${coord} in Packages palette`}
        {...packageBadgeClick}
      >
        PACKAGE
      </button>
    </div>
  );
}
