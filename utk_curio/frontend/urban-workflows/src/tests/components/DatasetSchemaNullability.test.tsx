import React from "react";
import { render, renderHook, screen, waitFor } from "@testing-library/react";

/**
 * #444: an inferred schema said every column was nullable. A field is now
 * nullable, not nullable, or not known, and the Schema tab shows the three.
 */

const mockPreview = jest.fn();
jest.mock("../../services/datasetCatalog", () => ({
  datasetCatalogApi: { preview: (...args: unknown[]) => mockPreview(...args) },
}));

import { DatasetSchemaPanel } from "../../components/datasets/catalog/DatasetSchemaPanel";
import { useDatasetResolvedSchema } from "../../components/datasets/catalog/useDatasetResolvedSchema";

function nullCell(name: string): HTMLElement {
  const row = screen.getByTitle(name).closest("div")?.parentElement as HTMLElement;
  return row.lastElementChild as HTMLElement;
}

beforeEach(() => mockPreview.mockReset());

test("the Schema tab tells nullable, not nullable and not known apart", () => {
  render(
    <DatasetSchemaPanel
      schema={{
        fields: [
          { name: "score", type: "number", nullable: true },
          { name: "gid", type: "string", nullable: false },
          { name: "name", type: "string" },
        ],
        fetching: false,
        unsupportedMessage: null,
      }}
    />,
  );

  expect(nullCell("score").textContent).toBe("null");
  expect(nullCell("gid").textContent).toBe("");
  expect(nullCell("gid").getAttribute("title")).toBeNull();
  expect(nullCell("name").textContent).toBe("");
  expect(nullCell("name").getAttribute("title")).toBe("Not known: no nulls in the rows read");
  expect(screen.getByText(/1 nullable/)).toBeTruthy();
});

test("an inferred schema reads a real sample, not one row", async () => {
  mockPreview.mockResolvedValue({ schema: { fields: [{ name: "gid", type: "string" }] } });
  const dataset = { id: "d1", title: "D1", format: "csv", origin: "imported" } as any;

  renderHook(() => useDatasetResolvedSchema(dataset));

  await waitFor(() => expect(mockPreview).toHaveBeenCalled());
  const options = mockPreview.mock.calls[0][1];
  expect(options.rowLimit).toBeGreaterThan(1);
});

test("a bundle's parts are not all marked nullable", async () => {
  mockPreview.mockResolvedValue({
    schema: { bundleParts: [{ label: "table", format: "parquet" }, { label: "meta", format: "json" }] },
  });
  const dataset = { id: "b1", title: "B1", format: "bundle", origin: "computed" } as any;

  const { result } = renderHook(() => useDatasetResolvedSchema(dataset));

  await waitFor(() => expect(result.current.fields).toHaveLength(2));
  for (const field of result.current.fields) {
    expect(field.nullable).toBeUndefined();
  }
});
