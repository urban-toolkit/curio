import React, { memo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faSpinner, faTriangleExclamation } from "@fortawesome/free-solid-svg-icons";
import type { PendingInstall } from "../../../../services/datasetCatalog";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import rowStyles from "./DatasetPaletteRows.module.css";
import packageCardStyles from "../../../packages/publishing/PackageCard.module.css";

/**
 * Non-interactive "Adding…" placeholder row shown in the dataset palette
 * while a dataset is being installed (node run auto-install, manual install, or
 * import). Mirrors DatasetRow's chrome with a spinner in place of the drag
 * handle; replaced by the real DatasetRow once the install lands.
 *
 * A failed install says so instead (#352). It used to be cleared as if it had
 * succeeded, which is the "entry flashes then disappears" of #217 - the toast
 * explains what happened, and the row should not contradict it by pretending
 * the work is still in progress or that it never started.
 */
export const DatasetInstallingRow = memo(function DatasetInstallingRow({
  pending,
}: {
  pending: PendingInstall;
}) {
  const failed = pending.status === "failed";
  return (
    <div
      className={`${packageStyles.packageKindRow} ${rowStyles.installingRow ?? ""}`}
      role="status"
      aria-busy={failed ? "false" : "true"}
      aria-label={failed ? `Could not add ${pending.label}` : `Adding ${pending.label}`}
    >
      <div className={`${packageStyles.packageKindRowDrag} ${rowStyles.datasetRowDrag}`}>
        <FontAwesomeIcon
          icon={failed ? faTriangleExclamation : faSpinner}
          spin={!failed}
          aria-hidden="true"
          className={`${packageStyles.packageKindDragIcon} ${rowStyles.datasetDragIcon}`}
        />
      </div>
      <div className={packageStyles.packageKindRowMeta}>
        <span className={packageStyles.packageKindRowLabel}>{pending.label}</span>
        <span className={packageCardStyles.cardMetaText}>
          {failed ? "Couldn't be added" : "Adding…"}
        </span>
      </div>
    </div>
  );
});
