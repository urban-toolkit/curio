import React, { useCallback, useMemo } from "react";
import type { NodeCategory, NodePackageMeta } from "../../../registry/types";
import { BUILTIN_PACKAGE_ID } from "../../../registry/packageKeys";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../constants/nodeCategoryShortLabels";
import { NODE_CATEGORY_KEY } from "../../../constants/nodeCategoryPalette";
import { formatForkOfSubtitle } from "../../../utils/forkPackageLineage";
import { usePackagePalette } from "../../../providers/PackagePaletteContext";
import { useHeaderIconDragClick } from "../../../utils/headerIconDragClick";
import styles from "./PackageMetaHeader.module.css";

export interface PackageMetaHeaderProps {
  /** The package this node came from. Required: the component dereferences it
   * unconditionally, and its only caller renders nothing without one. The
   * interface used to declare a required `package` that nobody passed and an
   * optional `pkg` that everybody did, so the call site was an error and every
   * use inside was possibly-undefined. */
  pkg: NodePackageMeta;
  category: NodeCategory;
  suggestionActive: boolean;
}

/**
 * Category + PACKAGE pills for the canvas node title bar (right of the kind label).
 * PACKAGE shows `packageId@major` in a tooltip and focuses that package in the left palette.
 *
 * The PACKAGE pill is withheld for ``curio.builtin`` (#218). The report says it
 * appears on "nodes that do not come from a package", which is not quite what
 * is happening -- every palette node comes from a package now, built-ins
 * included, so ``source === 'package'`` is true for all of them and the pill
 * rendered everywhere.
 *
 * The rule is about what the button DOES, not what built-ins are: its whole
 * effect is ``setActivePackageKey`` + ``setPaletteDockRevealCoord``, and the
 * Packages palette lists only third-party packages (``ToolsMenu`` filters the
 * builtin into the separate Built-in rail). So on a built-in node the pill is
 * an affordance for an action that cannot happen.
 */
export function PackageMetaHeader({ pkg, category, suggestionActive }: PackageMetaHeaderProps) {
  const { setActivePackageKey, setPaletteDockRevealCoord } = usePackagePalette();
  const coord = `${pkg.packageId}@${pkg.major}`;

  const packageTooltip = useMemo(() => {
    const lines = [coord];
    if (pkg.lineage != null) {
      const fork = formatForkOfSubtitle(pkg.lineage);
      lines.push(fork.text);
      if (fork.title) lines.push(fork.title);
    }
    lines.push("Click to open this package in the Packages palette");
    return lines.join("\n");
  }, [coord, pkg.lineage]);

  const focusPackageInPalette = useCallback(() => {
    if (suggestionActive) return;
    setActivePackageKey(coord);
    setPaletteDockRevealCoord(coord);
  }, [coord, setActivePackageKey, setPaletteDockRevealCoord, suggestionActive]);

  const packageBadgeClick = useHeaderIconDragClick(focusPackageInPalette);

  // Not `pkg.readOnly`: that marks a package the user may not edit, which is a
  // different question and is also true of packages the pill works fine for.
  const revealable = pkg.packageId !== BUILTIN_PACKAGE_ID;

  return (
    <div className={styles.pills} style={suggestionActive ? { pointerEvents: "none" } : undefined}>
      {/* Coloured by category, like the node's own left border. It used to be
          one flat peach for every category, so the pill named the category
          while the border beside it was the only thing showing it. */}
      <span
        className={`${styles.categoryBadge} ${
          (styles as Record<string, string>)[`categoryBadge_${NODE_CATEGORY_KEY[category]}`] ?? ""
        }`}
        title={NODE_CATEGORY_SHORT_LABEL[category]}
      >
        {NODE_CATEGORY_SHORT_LABEL[category]}
      </span>
      {revealable ? (
        <button
          type="button"
          className={styles.packageBadge}
          title={packageTooltip}
          aria-label={`Open package ${coord} in Packages palette`}
          {...packageBadgeClick}
        >
          PACKAGE
        </button>
      ) : null}
    </div>
  );
}
