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
import { isNodeLinkedToAnyDataset } from "../../../../services/datasetCatalog";
import { focusLinkedNodes } from "../../../../utils/focusDatasetNodes";
import { useToastContext } from "../../../../providers/ToastProvider";
import { CopyButton } from "../../../CopyButton";
import { datasetReferenceCode } from "../../../../services/datasetCatalog";


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
      // A node is linked when it references this dataset by any means:
      //  - created from the palette (datasetSource) or dropped onto it
      //    (datasetRefs / appliedDatasets) - including a group-created node that
      //    references this layer among its members;
      //  - producer: the node that generated this computed dataset.
      const isLinked = (n: { id: string; data: any }) =>
        isNodeLinkedToAnyDataset(n.data, [dataset.id]) || n.id === dataset.producerNodeId;
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
        {/* The rail sits beside the code editor, so this is where someone
            writing a node needs the reference. It is outside the meta button
            because that button selects the dataset's nodes on the canvas
            (#206). */}
        <CopyButton
          value={datasetReferenceCode(dataset)}
          label="Copy dataset reference"
          className={rowStyles.copyButton}
        />
      </div>
    </OverlayTrigger>
  );
});

/**
 * Collapsible parent row for a multilayer OSM PBF import. The header is not
 * draggable (it represents the whole import); expanding it reveals the
 * individual layer datasets, each an ordinary - still draggable - {@link
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

  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();

  // Highlight every node linked to this import: any node referencing a member
  // layer (individual-layer or dropped-on nodes), the full-group node (its
  // datasetSource is the group id), or a layer's producer. Mirrors the single
  // DatasetRow highlight so the parent behaves consistently.
  const selectOnCanvas = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const linkIds = [group.groupId, ...group.members.map((m) => m.id)];
      const producerIds = new Set(
        group.members.map((m) => m.producerNodeId).filter(Boolean) as string[],
      );
      const isLinked = (n: { id: string; data: any }) =>
        isNodeLinkedToAnyDataset(n.data, linkIds) || producerIds.has(n.id);
      if (focusLinkedNodes(reactFlow, isLinked) === 0) {
        showToast("No nodes on the canvas use this dataset", "info");
      }
    },
    [group.groupId, group.members, reactFlow, showToast],
  );

  return (
    <div className={rowStyles.groupBlock} data-osm-group-id={group.groupId}>
      {/* Tooltip is scoped to the header so hovering an expanded member shows the
          member's own tooltip, not the group's. */}
      <OverlayTrigger
        placement={tooltipPlacement}
        delay={OVERLAY_TRIGGER_DELAY_PROPS}
        overlay={
          <Tooltip>{`${group.title} · OSM PBF · ${layerCount} layer${layerCount === 1 ? "" : "s"}`}</Tooltip>
        }
      >
        <div className={rowStyles.groupHeader} data-dataset-id={group.groupId}>
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
          {/* Meta area highlights linked nodes (like a single row); the caret
              button owns expand/collapse so the two actions don't conflict. */}
          <button
            type="button"
            className={rowStyles.groupMetaButton}
            onClick={selectOnCanvas}
          >
            <span className={packageStyles.packageKindRowLabel}>{group.title}</span>
            <div className={rowStyles.rowMeta}>
              <span className={packageStyles.packageKindCategoryChip}>Imported</span>
              {time ? <span className={rowStyles.rowMetaText}>{time}</span> : null}
            </div>
          </button>
          <button
            type="button"
            className={rowStyles.groupCaretButton}
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${group.title}: OSM PBF import with ${layerCount} layer${layerCount === 1 ? "" : "s"}`}
          >
            <FontAwesomeIcon
              icon={open ? faChevronUp : faChevronDown}
              className={rowStyles.groupCaret}
            />
          </button>
        </div>
      </OverlayTrigger>
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
