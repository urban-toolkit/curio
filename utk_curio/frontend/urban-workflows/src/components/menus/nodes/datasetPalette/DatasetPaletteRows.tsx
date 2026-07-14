import React, { memo, useCallback, useMemo, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase, faChevronDown, faChevronUp } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import {
  beginDatasetDrag,
  beginDatasetDragWith,
  createOsmGroupDragPayload,
  endDatasetDrag,
  writeDatasetDragData,
  DATASET_FORMAT_LABEL,
  DatasetCatalogItem,
  datasetDisplayTitle,
  datasetSubtitle,
  datasetProvenanceLabel,
  type DatasetPaletteGroup,
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
import { useReactFlow } from "reactflow";
import { getDatasetSourceId } from "../../../../services/datasetCatalog";
import { focusLinkedNodes } from "../../../../utils/focusDatasetNodes";
import { useToastContext } from "../../../../providers/ToastProvider";


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
  const tooltipParts = [datasetDisplayTitle(dataset), metaParts].filter(Boolean);
  const formatChipClass =
    rowStyles[`chip_${dataset.format}` as keyof typeof rowStyles] ?? rowStyles.formatChip;

  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();

  const selectOnCanvas = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      // Two linkage directions:
      //  - consumer: node created from the palette, stamped datasetSource (not
      //    datasetRefs, which also covers datasets merely dropped onto a node);
      //  - producer: node that generated this computed dataset (producerNodeId).
      const isLinked = (n: { id: string; data: any }) =>
        getDatasetSourceId(n.data) === dataset.id || n.id === dataset.producerNodeId;
      if (focusLinkedNodes(reactFlow, isLinked) === 0) {
        showToast("No nodes on the canvas use this dataset", "info");
      }
    },
    [dataset.id, dataset.producerNodeId, reactFlow, showToast],
  );

  return (
    <OverlayTrigger
      placement={tooltipPlacement}
      delay={OVERLAY_TRIGGER_DELAY_PROPS}
      overlay={<Tooltip>{tooltipParts.join(" · ")}</Tooltip>}
    >
      <div className={packageStyles.packageKindRow} data-dataset-id={dataset.id}>
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
        <button type="button" className={packageStyles.packageKindRowMeta} onClick={selectOnCanvas}>
          <span className={packageStyles.packageKindRowLabel}>
            {datasetDisplayTitle(dataset)}
          </span>
          <span className={packageCardStyles.cardMetaText}>
            {datasetSubtitle(dataset)}
          </span>

          <div className={rowStyles.rowMeta}>
            <span className={packageStyles.packageKindCategoryChip}>
              {datasetProvenanceLabel(dataset.origin, dataset.format)}
            </span>

            {metaParts ? <span className={rowStyles.rowMetaText}>{metaParts}</span> : null}
            <DatasetConnectionBadge dataset={dataset} className={rowStyles.connBadge} />
          </div>
        </button>
      </div>
    </OverlayTrigger>
  );
});

/**
 * Collapsible parent row for a multilayer OSM PBF import. The header is not
 * draggable (it represents the whole import); expanding it reveals the
 * individual layer datasets, each an ordinary — still draggable — {@link
 * DatasetRow}. Grouping is computed upstream by ``groupDatasetsForPalette``.
 */
export const DatasetGroupRow = memo(function DatasetGroupRow({
  group,
  tooltipPlacement = "right",
}: {
  group: DatasetPaletteGroup;
  tooltipPlacement?: ToolsMenuTooltipSide;
}) {
  const [open, setOpen] = useState(false);
  const layerCount = group.members.length;
  const time = relativeTime(group.updatedAt);
  const osmChipClass = rowStyles.chip_osm ?? rowStyles.formatChip;
  // Dragging the parent creates one node loading ALL layers (the full import).
  const dragPayload = useMemo(() => createOsmGroupDragPayload(group), [group]);

  return (
    <div className={rowStyles.groupBlock} data-osm-group-id={group.groupId}>
      <div className={rowStyles.groupHeader}>
        <div
          className={`${packageStyles.packageKindRowDrag} ${rowStyles.datasetRowDrag} ${rowStyles.groupIconBox}`}
          draggable
          onDragStart={(event) => {
            writeDatasetDragData(event.dataTransfer, beginDatasetDragWith(dragPayload));
          }}
          onDragEnd={() => endDatasetDrag()}
          title={`Drag to add all ${layerCount} layer${layerCount === 1 ? "" : "s"} as one dataset`}
        >
          <FontAwesomeIcon
            icon={faDatabase}
            className={`${packageStyles.packageKindDragIcon} ${rowStyles.datasetDragIcon}`}
          />
          <span className={`${rowStyles.iconBadge} ${osmChipClass}`}>
            {DATASET_FORMAT_LABEL.osm}
          </span>
        </div>
        <button
          type="button"
          className={rowStyles.groupToggle}
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? "Collapse" : "Expand"} ${group.title} — OSM PBF import with ${layerCount} layer${layerCount === 1 ? "" : "s"}`}
        >
          <div className={rowStyles.groupHeaderMeta}>
            <span className={packageStyles.packageKindRowLabel}>{group.title}</span>
            <div className={rowStyles.rowMeta}>
              <span className={packageStyles.packageKindCategoryChip}>Imported</span>
              {time ? <span className={rowStyles.rowMetaText}>{time}</span> : null}
            </div>
          </div>
          <FontAwesomeIcon
            icon={open ? faChevronUp : faChevronDown}
            className={rowStyles.groupCaret}
          />
        </button>
      </div>
      {open ? (
        <div className={rowStyles.groupMembers} role="group" aria-label={`${group.title} layers`}>
          {group.members.map((member) => (
            <DatasetRow
              key={`${member.origin}:${member.id}`}
              dataset={member}
              tooltipPlacement={tooltipPlacement}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
});
