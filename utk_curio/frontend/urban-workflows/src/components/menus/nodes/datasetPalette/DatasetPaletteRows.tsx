import React, { memo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import {
  beginDatasetDrag,
  endDatasetDrag,
  writeDatasetDragData,
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetProvenanceLabel,
} from "../../../../services/datasetCatalog";
import {
  datasetCountCompact as datasetCount,
  relativeTimeOrEmpty as relativeTime,
} from "../../../datasets/catalog/datasetDetailHelpers";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import { OVERLAY_TRIGGER_DELAY_PROPS, type ToolsMenuTooltipSide } from "../toolsMenuPackagePalette";
import rowStyles from "./DatasetPaletteRows.module.css";
import packageCardStyles from "../../../packages/publishing/PackageCard.module.css";

import { DatasetConnectionBadge } from "../../../datasets/catalog/DatasetConnectionBadge";


function formatAbbreviation(dataset: DatasetCatalogItem): string {
  if (dataset.format === "geojson") return "GeoJSON";
  if (dataset.format === "json") return "JSON";
  if (dataset.format === "geotiff") return "GeoTIFF";
  if (dataset.format === "bundle") return "Bundle";
  return DATASET_FORMAT_LABEL[dataset.format].toUpperCase();
}

export const DatasetRow = memo(function DatasetRow({
  dataset,
  tooltipPlacement = "right",
}: {
  dataset: DatasetCatalogItem;
  tooltipPlacement?: ToolsMenuTooltipSide;
}) {
  const count = datasetCount(dataset);
  const time = relativeTime(dataset.updatedAt);
  const metaParts = [count, time].filter(Boolean).join(" · ");
  const tooltipParts = [dataset.title, metaParts].filter(Boolean);
  const formatChipClass =
    rowStyles[`chip_${dataset.format}` as keyof typeof rowStyles] ?? rowStyles.formatChip;

  return (
    <OverlayTrigger
      placement={tooltipPlacement}
      delay={OVERLAY_TRIGGER_DELAY_PROPS}
      overlay={<Tooltip>{tooltipParts.join(" · ")}</Tooltip>}
    >
      <div className={packageStyles.packageKindRow}>
        <div
          className={`${packageStyles.packageKindRowDrag} ${rowStyles.datasetRowDrag}`}
          draggable
          onDragStart={(event) => {
            writeDatasetDragData(event.dataTransfer, beginDatasetDrag(dataset));
          }}
          onDragEnd={() => endDatasetDrag()}
        >
          <FontAwesomeIcon
            icon={faDatabase}
            className={`${packageStyles.packageKindDragIcon} ${rowStyles.datasetDragIcon}`}
          />
          <span className={`${rowStyles.iconBadge} ${formatChipClass}`}>
            {formatAbbreviation(dataset)}
          </span>
        </div>
        <div className={packageStyles.packageKindRowMeta}>
          <span className={packageStyles.packageKindRowLabel}>
            {dataset.format == "parquet" ? dataset.dirName : dataset.title}
          </span>
          <span className={packageCardStyles.cardMetaText}>
            {dataset.format == "parquet" ? dataset.title : dataset.dirName}
          </span>

          <div className={rowStyles.rowMeta}>
            <span className={packageStyles.packageKindCategoryChip}>
              {datasetProvenanceLabel(dataset.origin, dataset.format)}
            </span>

            {metaParts ? <span className={rowStyles.rowMetaText}>{metaParts}</span> : null}
            <DatasetConnectionBadge dataset={dataset} className={rowStyles.connBadge} />
          </div>
        </div>
      </div>
    </OverlayTrigger>
  );
});
