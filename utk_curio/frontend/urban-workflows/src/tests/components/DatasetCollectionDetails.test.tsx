/**
 * A collection's details: what its files are, where they are, and Cache files
 * for a bucket's. A table combined from a storage source's files says so.
 */
import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

jest.mock("../../utils/authApi", () => ({ apiFetch: jest.fn(), getToken: () => "tok" }));
jest.mock("../../utils/backendUrl", () => ({ backendUrl: () => "http://backend.test" }));
jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: jest.fn(() => ({
    datasetId: "c1",
    upstream: { generatingNode: null, sourceDatasets: [], origin: "imported", originLabel: "Imported" },
    downstream: { consumingNodes: [], consumingDataflows: [], derivedDatasets: [] },
    status: { hasLineage: false, hasUnresolvedReferences: false, isPartial: false },
  })),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/datasets/catalog/useDatasetResolvedSchema", () => ({
  useDatasetResolvedSchema: jest.fn(() => ({
    fields: [], geometryType: null, fetching: false, unsupportedMessage: null,
  })),
}));
jest.mock("../../components/datasets/catalog/DatasetSchemaPanel", () => ({
  DatasetSchemaPanel: () => <div data-testid="schema-panel" />,
}));
jest.mock("../../components/datasets/catalog/DatasetTablePreview", () => ({
  DatasetTablePreview: () => <div data-testid="table-preview" />,
}));
jest.mock("../../components/datasets/catalog/DatasetDataflowUsage", () => ({
  useDatasetDataflowUsage: () => [],
  DatasetDataflowUsageSection: () => null,
}));

import { DatasetDetailPanel } from "../../components/datasets/catalog/DatasetDetailPanel";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const { apiFetch } = require("../../utils/authApi") as { apiFetch: jest.Mock };

const block = {
  kind: "images" as const,
  sourceId: "lake.example.bucket@1",
  sourceName: "Bucket",
  provider: "s3",
  resourceId: "pics",
  resource: "pics",
  path: "pics/*",
  fields: [],
  counts: { image: 2 },
  fileCount: 2,
  totalBytes: 4096,
  hasGps: true,
  probeErrors: 0,
  indexedAt: new Date().toISOString(),
  fingerprint: "f",
};

function item(over: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem {
  return {
    id: "imported.xc1@1",
    title: "Pictures",
    origin: "imported",
    format: "collection",
    uri: "",
    path: "/x/data/index.parquet",
    consumerNodeIds: [],
    updatedAt: new Date().toISOString(),
    tags: [],
    collection: block,
    lakeSource: { lakeId: "lake.example.bucket@1", lakeName: "Bucket", resourceId: "pics", fileCount: 2 },
    ...over,
  };
}

function status(over: Record<string, unknown> = {}) {
  return {
    datasetId: "imported.xc1@1",
    provider: "s3",
    local: false,
    fileCount: 2,
    totalBytes: 4096,
    cachedFiles: 0,
    cachedBytes: 0,
    samples: [{ fileId: "a".repeat(16), name: "x.jpg", kind: "image" }],
    ...over,
  };
}

async function renderPanel(dataset: DatasetCatalogItem) {
  await act(async () => {
    render(
      <MemoryRouter>
        <DatasetDetailPanel dataset={dataset} dataflowId={null} />
      </MemoryRouter>,
    );
  });
}

beforeEach(() => {
  apiFetch.mockReset();
  (global as any).fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
});

describe("a collection's details", () => {
  it("says what the files are and where they were indexed from", async () => {
    apiFetch.mockResolvedValue(status());
    await renderPanel(item());
    expect(screen.getByText("Collection", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bucket" })).toHaveAttribute(
      "href",
      "/catalog/lakes/lake.example.bucket%401",
    );
    expect(screen.getByText("2 images")).toBeInTheDocument();
    expect(screen.queryByText("Downloaded from")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
    expect(screen.getByText('curio_collection("imported.xc1@1")')).toBeInTheDocument();
  });

  it("draws its first files by id, with the token", async () => {
    apiFetch.mockResolvedValue(status());
    await renderPanel(item());
    expect((global as any).fetch).toHaveBeenCalledWith(
      `http://backend.test/api/datasets/imported.xc1%401/media/${"a".repeat(16)}?variant=thumb`,
      { headers: { Authorization: "Bearer tok" }, signal: expect.any(AbortSignal) },
    );
  });

  it("names its resource and says what its fields, CRS and footprints cover", async () => {
    apiFetch.mockResolvedValue(status({ local: true, provider: "folder" }));
    await renderPanel(
      item({
        collection: {
          ...block,
          kind: "rasters",
          resource: "orthos",
          resourceName: "Drone orthoimagery",
          fields: ["year", "tile"],
          fieldValues: [
            { name: "year", type: "int", distinct: 2, values: ["2023", "2024"] },
            { name: "tile", type: "str", distinct: 400, min: "tile_0001", max: "tile_0400" },
          ],
          crs: ["EPSG:32616"],
          bounds: [-87.631543, 41.881246, -87.631156, 41.881392],
        },
      }),
    );
    expect(screen.getByText(/· Drone orthoimagery/)).toBeInTheDocument();
    expect(screen.getByText("year 2023, 2024 · tile tile_0001 to tile_0400")).toBeInTheDocument();
    expect(screen.getByText("EPSG:32616")).toBeInTheDocument();
    expect(screen.getByText("41.8812, -87.6315 to 41.8814, -87.6312")).toBeInTheDocument();
  });

  it("stops following its Cache files job once the panel is closed", async () => {
    jest.useFakeTimers();
    try {
      // The poll in flight when the panel closes answers after it has.
      let answer: (job: unknown) => void = () => {};
      apiFetch.mockImplementation((path: string, opts?: RequestInit) => {
        if (path.endsWith("/cache") && opts?.method === "POST") {
          return Promise.resolve({ jobId: "j1", status: "queued", itemsDone: 0, itemsTotal: 2 });
        }
        if (path.startsWith("/api/datalakes/jobs/")) {
          return new Promise((resolve) => {
            answer = resolve;
          });
        }
        return Promise.resolve(status());
      });
      let view: ReturnType<typeof render> | undefined;
      await act(async () => {
        view = render(
          <MemoryRouter>
            <DatasetDetailPanel dataset={item()} dataflowId={null} />
          </MemoryRouter>,
        );
      });
      await act(async () => {
        screen.getByRole("button", { name: "Cache files" }).click();
      });
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      const polls = () => apiFetch.mock.calls.filter(([path]) => String(path).startsWith("/api/datalakes/jobs/")).length;
      expect(polls()).toBe(1);
      view!.unmount();
      await act(async () => {
        answer({ jobId: "j1", status: "running", itemsDone: 1, itemsTotal: 2 });
      });
      await act(async () => {
        jest.advanceTimersByTime(10000);
      });
      expect(polls()).toBe(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it("offers Cache files for a bucket's files and follows the job", async () => {
    apiFetch.mockImplementation((path: string, opts?: RequestInit) => {
      if (path.endsWith("/cache") && opts?.method === "POST") {
        return Promise.resolve({ jobId: "j1", status: "queued", itemsDone: 0, itemsTotal: 2 });
      }
      return Promise.resolve(status());
    });
    await renderPanel(item());
    expect(screen.getByText("0 of 2 files")).toBeInTheDocument();
    await act(async () => {
      screen.getByRole("button", { name: "Cache files" }).click();
    });
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/datalakes/collections/imported.xc1%401/cache",
      { method: "POST" },
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Caching…" })).toBeDisabled());
  });

  it("offers nothing to cache for a folder's files", async () => {
    apiFetch.mockResolvedValue(status({ local: true, provider: "folder", cachedFiles: 2 }));
    await renderPanel(item());
    expect(screen.queryByRole("button", { name: "Cache files" })).toBeNull();
    expect(screen.queryByText("On this machine")).toBeNull();
  });
});

describe("a table added from a storage source", () => {
  it("says it was combined, and from which source", async () => {
    await renderPanel(
      item({
        format: "parquet",
        collection: null,
        lakeSource: {
          lakeId: "lake.curio.example-storage@1",
          lakeName: "Example storage",
          resourceId: "air-quality",
          fileCount: 9,
          fetchedAt: new Date().toISOString(),
        },
      }),
    );
    expect(screen.getByText("Added from")).toBeInTheDocument();
    expect(screen.getByText("9 files")).toBeInTheDocument();
    expect(screen.getByText("air-quality")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
