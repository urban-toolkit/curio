import React, { memo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner } from "@fortawesome/free-solid-svg-icons";
import type { PendingInstall } from "../../../../services/datasetCatalog";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import rowStyles from "./DatasetPaletteRows.module.css";
import packageCardStyles from "../../../packages/publishing/PackageCard.module.css";

/**
 * Non-interactive "Adding…" placeholder row shown in the dataset palette
 * while a dataset is being installed (node run auto-install, manual install, or
 * import). Mirrors DatasetRow's chrome with a spinner in place of the drag
 * handle; replaced by the real DatasetRow once the install lands.
 */
export const DatasetInstallingRow = memo(function DatasetInstallingRow({
  pending,
}: {
  pending: PendingInstall;
}) {
  return (
    <div
      className={`${packageStyles.packageKindRow} ${rowStyles.installingRow ?? ""}`}
      role="status"
      aria-busy="true"
      aria-label={`Adding ${pending.label}`}
    >
      <div className={`${packageStyles.packageKindRowDrag} ${rowStyles.datasetRowDrag}`}>
        <FontAwesomeIcon
          icon={faSpinner}
          spin
          aria-hidden="true"
          className={`${packageStyles.packageKindDragIcon} ${rowStyles.datasetDragIcon}`}
        />
      </div>
      <div className={packageStyles.packageKindRowMeta}>
        <span className={packageStyles.packageKindRowLabel}>{pending.label}</span>
        <span className={packageCardStyles.cardMetaText}>Adding…</span>
      </div>
    </div>
  );
});
