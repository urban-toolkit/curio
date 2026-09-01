import React from "react";
import { render, screen } from "@testing-library/react";

// DatasetConnectionBadge pulls in FlowProvider and, through it, the registry
// and vega/vega-lite (ESM jest's transform does not handle). The badge is not
// what these tests are about.
jest.mock("../../components/datasets/catalog/DatasetConnectionBadge", () => ({
  DatasetConnectionBadge: () => null,
}));
import { DatasetCard } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCardProps } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCatalogItem } from "../../services/datasetCatalog/datasetCatalogTypes";

/**
 * Covers which actions a dataset card offers.
 *
 * The Delete gate is the interesting one. Hub rows started carrying
 * ``producerNodeId`` once publish began persisting lineage, which made the
 * "is this a computed asset?" test true for datasets belonging to someone
 * else - so a viewer browsing the shared catalog saw a Delete button the
 * backend then (correctly) refused with a 403. The owner is unaffected because
 * their own copy wins the dedup and arrives as ``origin: "computed"``.
 */

const card = (over: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem =>
  ({
    id: "computed.flow-1.n1",
    title: "Trips",
    origin: "computed",
    format: "csv",
    tags: [],
    updatedAt: "2026-01-01T00:00:00Z",
    ...over,
  } as unknown as DatasetCatalogItem);

const renderCard = (dataset: DatasetCatalogItem, props: Partial<DatasetCardProps> = {}) =>
  render(
    <DatasetCard
      dataset={dataset}
      isInstalled={false}
      isPublished={false}
      busy={false}
      onInstall={jest.fn()}
      onDelete={jest.fn()}
      {...props}
    />,
  );

const deleteButton = () => screen.queryByRole("button", { name: /^Delete$/i });

describe("DatasetCard delete affordance", () => {
  test("offers Delete on an account-level computed dataset", () => {
    renderCard(card(), { isInstalled: true });
    expect(deleteButton()).not.toBeNull();
  });

  test("offers Delete on a row identified only by its producer node", () => {
    renderCard(card({ origin: "imported", producerNodeId: "n1" } as never), { isInstalled: true });
    expect(deleteButton()).not.toBeNull();
  });

  test("hides Delete on a hub row even when it carries producer lineage", () => {
    // The regression: publish now persists producerNodeId into the hub
    // manifest, so this row looks computed without being the viewer's asset.
    renderCard(card({ origin: "hub", producerNodeId: "n1" } as never), { isInstalled: true });
    expect(deleteButton()).toBeNull();
  });

  test("offers Delete on a plain imported row — an upload the user owns", () => {
    // Deliberately inverted. An uploaded file is an account-level asset just
    // like a node output, and it was the one thing with no way to delete it on
    // purpose: it went only as a side effect of removing it from the last
    // dataflow that used it.
    renderCard(card({ origin: "imported" } as never), { isInstalled: true });
    expect(deleteButton()).not.toBeNull();
  });

  test("still hides Delete on a catalog row the user installed", () => {
    renderCard(
      card({ origin: "imported", dirName: "data.urbanlab.demo@1" } as never),
      { isInstalled: true },
    );
    expect(deleteButton()).toBeNull();
  });

  test("hides Delete when no handler is supplied", () => {
    renderCard(card(), { isInstalled: true, onDelete: undefined });
    expect(deleteButton()).toBeNull();
  });
});

describe("DatasetCard primary action copy", () => {
  test("an unadded dataset offers Add to dataflow", () => {
    renderCard(card());
    expect(screen.getByRole("button", { name: "Add to dataflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  });

  test("an added dataset offers Remove from dataflow", () => {
    renderCard(card(), { isInstalled: true, onUninstall: jest.fn() });
    expect(
      screen.getByRole("button", { name: "Remove from dataflow" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Uninstall" })).toBeNull();
  });
});
