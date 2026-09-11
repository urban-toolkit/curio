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
  it("offers Add to project when not installed", () => {
    renderCard();
    expect(button("Add to project")).toBeTruthy();
    expect(button("Remove from project")).toBeNull();
  });

  it("offers Remove from project once installed", () => {
    renderCard({ isInstalled: true, onUninstall: jest.fn() });
    expect(button("Remove from project")).toBeTruthy();
    expect(button("Add to project")).toBeNull();
  });

  it("passes the dataset through to onInstall", () => {
    const onInstall = jest.fn();
    const item = dataset();
    render(<DatasetCard {...base} dataset={item} onInstall={onInstall} />);
    fireEvent.click(button("Add to project")!);
    expect(onInstall).toHaveBeenCalledWith(item);
  });

  it("disables its actions while the drawer is busy", () => {
    renderCard({ busy: true });
    expect(button("Add to project")!.hasAttribute("disabled")).toBe(true);
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

  it("offers Delete on an upload, which has no producer node", () => {
    // Inverted deliberately: an uploaded file is the user's own account-level
    // asset and now has an explicit Delete. It previously had none at all.
    renderCard({
      dataset: dataset({
        origin: "imported",
        producerNodeId: null,
        dirName: "imported.my-upload@1",
      }),
      onDelete: jest.fn(),
    });
    expect(button("Delete")).toBeTruthy();
  });

  it("hides Delete when no handler is supplied", () => {
    renderCard({ dataset: dataset({ origin: "computed", producerNodeId: "n" }) });
    expect(button("Delete")).toBeNull();
  });
});

describe("DatasetCard - no publish affordance at all", () => {
  // The card used to carry Publish / Unpublish, gated on whether the dataset
  // was the user's own. The gate was right and the PLACE was wrong: publishing
  // puts an item into the catalog everyone on this Curio shares, which is a
  // decision about the item and not about the project this card sits in. It now
  // lives in the Data Catalog page's detail drawer, next to the account-level
  // add/remove, where the ownership gate still applies.
  //
  // On a card it also sat in a scrolling grid, one stray click from a browse
  // gesture, and it was the thing the user asked three times to have removed.
  const ownUpload = { dirName: "imported.my-upload@1", origin: "imported" as const };

  it("offers no Publish, even for the user's own upload", () => {
    renderCard({ dataset: dataset(ownUpload) });
    expect(button("Publish")).toBeNull();
  });

  it("offers no Unpublish, even for the user's own published upload", () => {
    renderCard({ dataset: dataset(ownUpload) });
    expect(button("Unpublish")).toBeNull();
  });

  it("still offers the actions that ARE about this project", () => {
    // Removing the publish control must not have taken the per-project ones.
    renderCard({ dataset: dataset(ownUpload), isInstalled: true, onUninstall: jest.fn() });
    expect(button("Remove from project")).toBeTruthy();
  });

  it("offers the one way into the item's details, under the square", () => {
    renderCard({ dataset: dataset(ownUpload), onOpenDetails: jest.fn() });
    // Hidden from the a11y tree: the avatar above it already carries the same
    // accessible name for the same action, and two controls with one name is a
    // strict-mode ambiguity. So query the text, not the role.
    expect(screen.getByText("View details")).toBeTruthy();
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
