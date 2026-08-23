import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

// DatasetCard -> DatasetConnectionBadge -> useDatasetLineage -> FlowProvider
// -> the node registry, which pulls in the vega behaviour. Those modules do
// not load under jsdom; same workaround as packageStarterInjection.test.tsx.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });
import { DatasetCard } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCatalogItem } from "../../services/datasetCatalog/datasetCatalogTypes";

/**
 * `DatasetCard` had no test file at all, despite carrying the most consequential
 * gate in the Data Catalog: Delete.
 *
 * A hub row is someone else's published dataset. Those rows now carry a
 * `producerNodeId`, so the naive "is this computed?" check would offer Delete on
 * them — a button the backend correctly 403s. The owner still sees their own
 * asset as the merged `origin: "computed"` row, so hiding it on hub rows costs
 * them nothing. Pinned here because the condition is subtle and the failure mode
 * (offering a destructive action that cannot succeed) is user-visible.
 */

const dataset = (over: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem =>
  ({
    id: "data.urbanlab.demo",
    dirName: "data.urbanlab.demo@1",
    title: "Demo Dataset",
    description: "",
    format: "geojson",
    origin: "hub",
    publisher: "Data Catalog",
    tags: [],
    installed: false,
    updatedAt: "2026-01-01T00:00:00Z",
    producerNodeId: null,
    ...over,
  } as unknown as DatasetCatalogItem);

const base = {
  isInstalled: false,
  isPublished: false,
  busy: false,
  onInstall: jest.fn(),
};

const renderCard = (over: Record<string, unknown> = {}) =>
  render(<DatasetCard {...(base as never)} dataset={dataset()} {...(over as never)} />);

const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => jest.clearAllMocks());

describe("DatasetCard — primary action", () => {
  it("offers Add to dataflow when not installed", () => {
    renderCard();
    expect(button("Add to dataflow")).toBeTruthy();
    expect(button("Remove from dataflow")).toBeNull();
  });

  it("offers Remove from dataflow once installed", () => {
    renderCard({ isInstalled: true, onUninstall: jest.fn() });
    expect(button("Remove from dataflow")).toBeTruthy();
    expect(button("Add to dataflow")).toBeNull();
  });

  it("passes the dataset through to onInstall", () => {
    const onInstall = jest.fn();
    const item = dataset();
    render(<DatasetCard {...(base as never)} dataset={item} onInstall={onInstall} />);
    fireEvent.click(button("Add to dataflow")!);
    expect(onInstall).toHaveBeenCalledWith(item);
  });

  it("disables its actions while the drawer is busy", () => {
    renderCard({ busy: true });
    expect(button("Add to dataflow")!.hasAttribute("disabled")).toBe(true);
  });
});

describe("DatasetCard — Delete gating", () => {
  it("never offers Delete on a hub row, even one carrying a producer node", () => {
    renderCard({
      dataset: dataset({ origin: "hub", producerNodeId: "node-1" }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeNull();
  });

  it("offers Delete on the owner's computed row", () => {
    renderCard({
      dataset: dataset({ origin: "computed", producerNodeId: "node-1" }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeTruthy();
  });

  it("offers Delete on an imported row that has a producer node", () => {
    renderCard({
      dataset: dataset({ origin: "imported", producerNodeId: "node-1" }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeTruthy();
  });

  it("hides Delete on a plain imported row with no producer", () => {
    renderCard({
      dataset: dataset({ origin: "imported", producerNodeId: null }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeNull();
  });

  it("hides Delete when no handler is supplied", () => {
    renderCard({ dataset: dataset({ origin: "computed", producerNodeId: "n" }) });
    expect(button("Delete")).toBeNull();
  });
});

describe("DatasetCard — publish affordances", () => {
  it("offers Publish when allowed and not yet published", () => {
    renderCard({ onPublish: jest.fn(), publishAllowed: true });
    expect(button("Publish")).toBeTruthy();
  });

  it("hides Publish when the server forbids it", () => {
    renderCard({ onPublish: jest.fn(), publishAllowed: false });
    expect(button("Publish")).toBeNull();
  });

  it("does not offer Publish again once published", () => {
    renderCard({ onPublish: jest.fn(), publishAllowed: true, isPublished: true });
    expect(button("Publish")).toBeNull();
  });
});
