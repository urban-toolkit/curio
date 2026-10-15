import React from "react";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase, faSpinner, faUpload } from "@fortawesome/free-solid-svg-icons";
import { dataTypeVisual } from "../../constants/dataTypeVisuals";
import type { LoaderDataType } from "../../services/datasetCatalog/loaderProfile";
import styles from "./DataLoader.module.css";

/** The type's colours as the custom properties the stylesheet reads. */
export function dataTypeStyle(type: LoaderDataType): CSS.Properties {
  const visual = dataTypeVisual(type);
  return {
    ["--type-fg" as any]: visual.fg,
    ["--type-bg" as any]: visual.bg,
    ["--type-on-tint" as any]: visual.onTint,
  };
}

/**
 * The typed database: a tile in the type's tint, the database in its colour,
 * the type's glyph as a badge at the bottom right. While a background run is
 * finding the type, the badge is a spinner.
 */
export function DataLoaderGlyph({
  dataType,
  detecting = false,
  small = false,
}: {
  dataType: LoaderDataType;
  detecting?: boolean;
  small?: boolean;
}) {
  const visual = dataTypeVisual(dataType);
  const badge = detecting ? faSpinner : visual.glyph;
  return (
    <span
      className={small ? `${styles.glyph} ${styles.glyphSmall}` : styles.glyph}
      style={dataTypeStyle(dataType)}
      aria-hidden="true"
      data-testid="data-loader-glyph"
      data-data-type={dataType}
    >
      <FontAwesomeIcon icon={faDatabase} className={styles.db} />
      {badge ? (
        <span className={styles.badge}>
          <FontAwesomeIcon icon={badge} className={detecting ? styles.spin : undefined} />
        </span>
      ) : null}
    </span>
  );
}

/**
 * A folded loader: the Data Loading arrow and the typed database on one row,
 * the type's label under them. Every chip has the same box, whatever its
 * label (utils/loaderView LOADER_CHIP_*).
 */
export function DataLoaderChip({
  dataType,
  detecting = false,
}: {
  dataType: LoaderDataType;
  detecting?: boolean;
}) {
  const label = detecting ? "…" : dataTypeVisual(dataType).label;
  return (
    <span className={styles.chip} style={dataTypeStyle(dataType)} data-testid="data-loader-chip">
      <FontAwesomeIcon icon={faUpload} className={styles.chipArrow} aria-hidden="true" />
      <DataLoaderGlyph dataType={dataType} detecting={detecting} small />
      <span className={styles.chipLabel} aria-hidden="true">
        {label}
      </span>
    </span>
  );
}
