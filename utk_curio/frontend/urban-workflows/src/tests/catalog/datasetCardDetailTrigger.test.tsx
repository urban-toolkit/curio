import React from "react";
import { render, screen } from "@testing-library/react";

// The badge reaches useDatasetLineage -> FlowProvider -> the node registry ->
// vega, which ships ESM that jest does not transform. It renders no button and
// is irrelevant to what this file asserts.
jest.mock("../../components/datasets/catalog/DatasetConnectionBadge", () => ({
  DatasetConnectionBadge: () => null,
}));

import { DatasetCard } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

/**
 * One control per card opens the detail modal.
 *
 * The card grew a second one: `CatalogItemRowHeader` was handed the same
 * `onClick` *and* the same `buttonLabel` as the format avatar, so a single card
 * rendered two buttons whose accessible name was the identical
 * ``View <title> (GeoJSON) details``. Every Playwright selector that reaches a
 * dataset's details goes through that name, so all three e2e tests that open a
 * dataset (`test_dataset_export`, `test_dataset_lineage_e2e`) failed with a
 * strict-mode violation: "resolved to 2 elements".
 *
 * Asserted on the rendered accessible name rather than on the source, because
 * the duplication was in what the tree exposes, not in what the file says.
 */

const dataset: DatasetCatalogItem = {
  id: "data.urbanlab.chicago-community-areas",
  title: "Chicago Community Areas",
  origin: "hub",
  format: "geojson",
  uri: "data/chicago-community-areas.geojson",
  dirName: "data.urbanlab.chicago-community-areas@1",
  consumerNodeIds: [],
  updatedAt: "2026-08-25T00:00:00Z",
  tags: ["boundaries"],
};

const renderCard = (props: Partial<React.ComponentProps<typeof DatasetCard>> = {}) =>
  render(
    <DatasetCard
      dataset={dataset}
      isInstalled={false}
      isPublished={false}
      busy={false}
      onInstall={() => undefined}
      onOpenDetails={() => undefined}
      {...props}
    />,
  );

describe("dataset card detail trigger", () => {
  test("exposes exactly one control named for the dataset's details", () => {
    renderCard();
    const triggers = screen.getAllByRole("button", {
      name: /^View Chicago Community Areas \(/,
    });
    expect(triggers).toHaveLength(1);
  });

  test("that control is the format avatar, and it opens the details", () => {
    const onOpenDetails = jest.fn();
    renderCard({ onOpenDetails });

    screen
      .getByRole("button", { name: "View Chicago Community Areas (GeoJSON) details" })
      .click();

    expect(onOpenDetails).toHaveBeenCalledWith(dataset);
  });

  test("the row header is presentational", () => {
    renderCard();
    // It carries the format badge, which stays visible...
    expect(screen.getByText("GeoJSON")).toBeInTheDocument();
    // ...but the kind label is no longer an interactive fallback name.
    expect(screen.queryByRole("button", { name: "Dataset" })).toBeNull();
  });
});
