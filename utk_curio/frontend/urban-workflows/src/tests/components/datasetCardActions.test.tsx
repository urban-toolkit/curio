import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

// DatasetCard -> DatasetConnectionBadge -> useDatasetLineage -> FlowProvider
// -> the node registry, which pulls in the vega behaviour. Those modules do
// not load under jsdom; same workaround as packageStarterInjection.test.tsx.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });
import { DatasetCard } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCardProps } from "../../components/datasets/catalog/DatasetCard";
import type { DatasetCatalogItem } from "../../services/datasetCatalog/datasetCatalogTypes";

/**
 * `DatasetCard` had no test file at all, despite carrying the most consequential
 * gate in the Data Catalog: Delete.
 *
 * A hub row is someone else's published dataset. Those rows now carry a
 * `producerNodeId`, so the naive "is this computed?" check would offer Delete on
 * them - a button the backend correctly 403s. The owner still sees their own
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

const renderCard = (over: Partial<DatasetCardProps> = {}) =>
  render(<DatasetCard {...base} dataset={dataset()} {...over} />);

const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => jest.clearAllMocks());

describe("DatasetCard - primary action", () => {
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
    render(<DatasetCard {...base} dataset={item} onInstall={onInstall} />);
    fireEvent.click(button("Add to dataflow")!);
    expect(onInstall).toHaveBeenCalledWith(item);
  });

  it("disables its actions while the drawer is busy", () => {
    renderCard({ busy: true });
    expect(button("Add to dataflow")!.hasAttribute("disabled")).toBe(true);
  });
});

describe("DatasetCard - Delete gating", () => {
  it("never offers Delete on a hub row, even one carrying a producer node", () => {
    renderCard({
      dataset: dataset({ origin: "hub", producerNodeId: "node-1" }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeNull();
  });

  // These two now name the store folder, because that is what decides. The
  // fixture's default is a CATALOG folder (`data.urbanlab.demo@1`), so leaving
  // it implicit described a catalog dataset while claiming to describe the
  // user's own - the ambiguity the old `origin !== "hub"` guard fell into.
  it("offers Delete on the owner's computed row", () => {
    renderCard({
      dataset: dataset({
        origin: "computed",
        producerNodeId: "node-1",
        dirName: "computed.flow-1.node-1@1",
      }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeTruthy();
  });

  it("offers Delete on the owner's computed row once it reads as imported", () => {
    // Installing a dataset into a dataflow flips its origin to "imported"; the
    // owner's own asset keeps its `computed.*` folder and stays deletable.
    renderCard({
      dataset: dataset({
        origin: "imported",
        producerNodeId: "node-1",
        dirName: "computed.flow-1.node-1@1",
      }),
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

describe("DatasetCard - publish affordances", () => {
  // The default fixture is a CATALOG dataset (`data.urbanlab.demo@1`), i.e.
  // something the installation shipped. Publishing means "put this into the
  // catalog everyone on this Curio shares" - it is already there, and the
  // backend has no guard, so the button would write a duplicate.
  const ownUpload = { dirName: "imported.my-upload@1", origin: "imported" as const };
  const ownOutput = { dirName: "computed.flow-1.n2@1", origin: "computed" as const };

  it("offers Publish for the user's own upload", () => {
    renderCard({
      dataset: dataset(ownUpload),
      onPublish: jest.fn(),
      publishAllowed: true,
    });
    // "Publish…", not "Publish": the ellipsis says a confirmation follows, and
    // the sentence case keeps the ACTION from reading as a status chip.
    expect(button("Publish…")).toBeTruthy();
  });

  it("offers Publish for an output the user's own node computed", () => {
    renderCard({
      dataset: dataset(ownOutput),
      onPublish: jest.fn(),
      publishAllowed: true,
    });
    expect(button("Publish…")).toBeTruthy();
  });

  it("hides Publish for a dataset that came from the shared catalog", () => {
    // The reported confusion: every dataset offered to publish itself back
    // into the catalog it was installed from.
    renderCard({ onPublish: jest.fn(), publishAllowed: true });
    expect(button("Publish…")).toBeNull();
  });

  it("still hides Publish for a catalog dataset that has been installed", () => {
    // Installing flips `origin` from "hub" to "imported", so origin alone
    // cannot tell an install from an upload - the store folder can.
    renderCard({
      dataset: dataset({ origin: "imported", installed: true }),
      onPublish: jest.fn(),
      publishAllowed: true,
    });
    expect(button("Publish…")).toBeNull();
  });

  it("hides Publish when the server forbids it", () => {
    renderCard({
      dataset: dataset(ownUpload),
      onPublish: jest.fn(),
      publishAllowed: false,
    });
    expect(button("Publish…")).toBeNull();
  });

  it("does not offer Publish again once published", () => {
    renderCard({
      dataset: dataset(ownUpload),
      onPublish: jest.fn(),
      publishAllowed: true,
      isPublished: true,
    });
    expect(button("Publish…")).toBeNull();
  });
});

describe("DatasetCard - Delete is for the user's own assets only", () => {
  // Deleting removes an account-level dataset from the Data Catalog. Offering
  // it for something the installation shipped makes no sense, and the backend
  // 403s it - so the affordance must not be there in the first place.
  it("offers Delete for a dataset the user's own node computed", () => {
    renderCard({
      dataset: dataset({
        origin: "computed",
        producerNodeId: "n1",
        dirName: "computed.flow-1.n1@1",
      }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeTruthy();
  });

  it("hides Delete for a catalog dataset", () => {
    renderCard({
      dataset: dataset({ origin: "hub", producerNodeId: "n1" }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeNull();
  });

  it("hides Delete for a catalog dataset the user merely INSTALLED", () => {
    // The hole the old `origin !== "hub"` guard left: installing flips origin
    // to "imported" while the `data.*` store folder stays, so a published
    // computed dataset slipped through and offered a Delete the backend 403s.
    renderCard({
      dataset: dataset({
        origin: "imported",
        installed: true,
        producerNodeId: "n1",
        dirName: "data.urbanlab.demo@1",
      }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeNull();
  });
});
