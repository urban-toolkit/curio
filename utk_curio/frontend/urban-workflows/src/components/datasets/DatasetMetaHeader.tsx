import React, { useCallback, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase } from "@fortawesome/free-solid-svg-icons";
import {
  DatasetNodeSource,
  DATASET_FORMAT_LABEL,
  datasetProvenanceLabel,
} from "../../services/datasetCatalog";
import { useDatasetPalette } from "../../providers/DatasetPaletteContext";
import { useHeaderIconDragClick } from "../../utils/headerIconDragClick";
import styles from "./DatasetMetaHeader.module.css";

export interface DatasetMetaHeaderProps {
  source: DatasetNodeSource;
  suggestionActive?: boolean;
}

/**
 * DATASET pill for the canvas node title bar — rendered only on nodes created
 * from the dataset palette (see ``DatasetNodeSource``). Clicking it reveals the
 * linked installed listing in the dataset palette. Independent of the PACKAGE
 * pill: a node may show both at once.
 */
export function DatasetMetaHeader({ source, suggestionActive = false }: DatasetMetaHeaderProps) {
  const { setDatasetRevealId } = useDatasetPalette();

  const tooltip = useMemo(() => {
    const lines = [source.title];
    const meta = [datasetProvenanceLabel(source.origin), DATASET_FORMAT_LABEL[source.format]]
      .filter(Boolean)
      .join(" · ");
    if (meta) lines.push(meta);
    lines.push("Click to reveal in the dataset palette");
    return lines.join("\n");
  }, [source.title, source.origin, source.format]);

  const revealInPalette = useCallback(() => {
    if (suggestionActive) return;
    setDatasetRevealId(source.datasetId);
  }, [source.datasetId, setDatasetRevealId, suggestionActive]);

  const badgeClick = useHeaderIconDragClick(revealInPalette);

  return (
    <div className={styles.pills} style={suggestionActive ? { pointerEvents: "none" } : undefined}>
      <button
        type="button"
        className={styles.datasetBadge}
        title={tooltip}
        aria-label={`Reveal dataset ${source.title} in the dataset palette`}
        {...badgeClick}
      >
        <FontAwesomeIcon icon={faDatabase} className={styles.icon} aria-hidden />
        DATASET
      </button>
    </div>
  );
}
