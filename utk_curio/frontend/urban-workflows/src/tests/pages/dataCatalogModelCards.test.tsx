/**
 * A Data Catalog card for an ONNX model or a NetCDF file names its format and
 * shows its size, and counts no rows: both are stored as the file itself, and
 * neither has rows to count.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { DataCatalogBrowseCard } from "../../pages/dataCatalog/DataCatalogBrowseCard";
import { formatBytes } from "../../pages/dataCatalog/dataCatalogBrowseFormat";
import type { DatasetCatalogItem, DatasetFormat } from "../../services/datasetCatalog";

const SIZE = 34_000_000;

function dataset(format: DatasetFormat): DatasetCatalogItem {
  return {
    id: `imported.x${format}`,
    title: format === "onnx" ? "Deep Umbra" : "WRF rain",
    origin: "imported",
    format,
    uri: `curio://datasets/imported.x${format}@1`,
    consumerNodeIds: [],
    updatedAt: "2026-10-04T00:00:00Z",
    tags: [format, "imported"],
    sizeBytes: SIZE,
    rowCount: null,
    featureCount: null,
  } as DatasetCatalogItem;
}

describe.each([
  ["onnx", "ONNX"],
  ["netcdf", "NetCDF"],
] as const)("a %s card", (format, label) => {
  it("names its format and shows its size, with no row count", () => {
    const { container } = render(
      <DataCatalogBrowseCard
        dataset={dataset(format)}
        selected={false}
        onSelect={() => {}}
        onViewDetails={() => {}}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(`${formatBytes(SIZE)} | 0 nodes consume`)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\brows\b|feat\./);
  });
});
