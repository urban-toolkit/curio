/**
 * A shared guest is offered no shared-catalog writes (#222).
 *
 * Reported as "a shared guest can delete published datasets". The interesting
 * part is why the existing ownership rule does not catch it: every guest
 * sign-in resolves to ONE ``User`` row, so a dataset a guest published records
 * that shared account as its publisher, and the next guest along passes
 * ``publisher === str(caller)`` on it. Ownership cannot separate two principals
 * that are the same principal.
 *
 * The authoritative fix is server-side
 * (``utk_curio/backend/tests/test_datasets/test_guest_catalog_writes.py``); this
 * covers the affordance, so the UI does not offer a write that can only 403.
 *
 * Note what is NOT asserted here: that a guest loses Delete on their own
 * imported/computed datasets. They keep it, and the backend keeps allowing it —
 * the rule is about state other accounts can see, not about the guest store.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// UserProvider imports refreshPackageRegistry, which drags in the registry ->
// adapters -> vega chain that will not load under jsdom. Same stub the other
// suites that touch UserContext use.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

// The drawer's hero fetches a preview on mount. Nothing here is about the
// preview, and its async setState lands after the assertions as an act()
// warning, so stub it out rather than wait on it.
jest.mock("../../pages/dataHub/DataCatalogGeoPreview", () => ({
  DataCatalogGeoPreview: () => null,
}));

import { DataCatalogBrowseDrawer } from "../../pages/dataHub/DataCatalogBrowseDrawer";
import { UserContext } from "../../providers/UserProvider";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

/** An account-owned dataset: ``imported.`` store folder ⇒ isUserOwnedDataset. */
const OWN_DATASET = {
  id: "imported.mine",
  dirName: "imported.mine@1",
  title: "My upload",
  format: "csv",
  origin: "imported",
  updatedAt: "2026-01-01T00:00:00Z",
} as unknown as DatasetCatalogItem;

function renderDrawer(isSharedGuest: boolean) {
  const ctx = { isSharedGuest } as any;
  return render(
    <UserContext.Provider value={ctx}>
      <DataCatalogBrowseDrawer
        dataset={OWN_DATASET}
        publishingId={null}
        catalogPublishAllowed
        onPublish={jest.fn()}
        onUnpublish={jest.fn()}
        onAddToAllProjects={jest.fn()}
        onRemoveFromAllProjects={jest.fn()}
        onClose={jest.fn()}
        onViewDetails={jest.fn()}
      />
    </UserContext.Provider>,
  );
}

/** The pill renders as Publish or Unpublish; either one is a shared-catalog write. */
function publishControl() {
  return screen.queryByRole("button", { name: /publish/i });
}

describe("the publish control on a dataset the account owns", () => {
  test("a signed-in account is offered it", () => {
    renderDrawer(false);
    // Guards the negative test below: if the control were absent for everyone,
    // that test would pass while proving nothing.
    expect(publishControl()).not.toBeNull();
  });

  test("a shared guest is not", () => {
    renderDrawer(true);
    expect(publishControl()).toBeNull();
  });
});
