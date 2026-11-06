/**
 * The pin of the canvas's Discovery Catalog drawer (#1352).
 *
 * Pinned, the drawer stays open while the canvas, the palette and the top bar
 * keep working: its root carries data-pinned, on which the shell's stylesheet
 * takes the pointer off the root and the scrim, and its panel is not a modal
 * dialog. Unpinned, it is one, over a scrim, and the scrim closes it.
 *
 * The drawer's shell, header and search row are real. The sources, the search
 * and what a source adds are mocked: none of them is under test, and the
 * drawer lists no source.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

const mockCatalog = { data: { sources: [] }, loading: false, error: null, reload: () => undefined };
const mockSearch = { data: { sources: [], resources: [] }, loading: false, searched: false };
jest.mock("../../services/discoveryCatalog", () => ({
  ...jest.requireActual("../../services/discoveryCatalog"),
  useDiscoveryCatalog: () => mockCatalog,
  useDiscoverySearch: () => mockSearch,
}));
jest.mock("../../pages/discovery/useDiscoveryAcquisition", () => ({
  useDiscoveryAcquisition: () => ({}),
}));
jest.mock("../../pages/discovery/DiscoveryFederatedRows", () => ({ DiscoveryFederatedRows: () => null }));
jest.mock("../../pages/discovery/DiscoverySourceDetail", () => ({ DiscoverySourceBody: () => null }));
jest.mock("../../pages/discovery/DiscoverySourceCard", () => ({ DiscoverySourceCard: () => null }));
jest.mock("../../pages/discovery/DiscoverySourceDetailModal", () => ({ DiscoverySourceDetailModal: () => null }));
jest.mock("../../components/datasets/catalog/datasetDetailsContext", () => ({
  useDatasetDetails: () => ({ openDatasetDetails: jest.fn() }),
}));
jest.mock("../../providers/modelCatalog", () => ({
  useModelCatalogDrawer: () => ({ openModelCatalogDrawer: jest.fn() }),
}));

import { DiscoveryCatalogDrawer } from "../../components/discovery/catalog/DiscoveryCatalogDrawer";

const ROOT = '[data-curio-discovery-catalog-drawer="true"]';

test("pinned, the drawer lets the page work and is not modal; unpinned, it is modal", () => {
  const close = jest.fn();
  render(<DiscoveryCatalogDrawer presented onRequestClose={close} onExitComplete={jest.fn()} />);
  const dialog = screen.getByRole("dialog", { name: "Discovery Catalog" });
  const root = document.querySelector(ROOT);
  expect(root).not.toHaveAttribute("data-pinned");
  expect(dialog).toHaveAttribute("aria-modal", "true");

  fireEvent.click(within(dialog).getByRole("button", { name: "Pin drawer open" }));
  expect(root).toHaveAttribute("data-pinned", "true");
  expect(dialog).not.toHaveAttribute("aria-modal");
  // The pin still keeps it open on a click that reaches the scrim, and on Escape.
  fireEvent.click(screen.getByRole("button", { name: "Close discovery catalog" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(close).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Unpin drawer" }));
  expect(root).not.toHaveAttribute("data-pinned");
  expect(dialog).toHaveAttribute("aria-modal", "true");
  fireEvent.click(screen.getByRole("button", { name: "Close discovery catalog" }));
  expect(close).toHaveBeenCalledTimes(1);
});
