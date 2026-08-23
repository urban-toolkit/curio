import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PackageCard } from "../../components/packages/publishing/PackageCard";
import type { PackagePayload } from "../../api/packagesApi";

/**
 * Which action a package card offers is a pure function of its props, and it had
 * no test — even though the labels have been renamed three times in the last
 * twenty commits and the e2e tests key on them.
 *
 * The invariant worth pinning hardest is `curio.builtin@*`: it ships with every
 * instance and cannot be uninstalled or published, so its card must offer
 * nothing at all. A regression there hands users buttons the backend answers
 * with a 4xx.
 */

const pkg = (over: Partial<PackagePayload> = {}): PackagePayload =>
  ({
    dirName: "me.demo@1",
    packageId: "me.demo",
    name: "Demo",
    version: "1.0.0",
    publisher: "Tests",
    description: "",
    templates: [{ id: "me.demo/demo" }],
    lineage: null,
    familyKey: "me.demo@1",
    ...over,
  } as unknown as PackagePayload);

const base = {
  isInstalled: false,
  hasUpdate: false,
  catalogRow: undefined,
  busy: false,
  catalogPublishAllowed: false,
  onInstall: jest.fn(),
};

const renderCard = (over: Record<string, unknown> = {}) =>
  render(<PackageCard {...(base as never)} pkg={pkg()} {...(over as never)} />);

const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => jest.clearAllMocks());

describe("PackageCard — primary action", () => {
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

  it("offers Update when installed with a newer catalog version", () => {
    renderCard({
      isInstalled: true,
      hasUpdate: true,
      catalogRow: pkg({ version: "2.0.0" }),
      onUninstall: jest.fn(),
    });
    expect(button("Update")).toBeTruthy();
    expect(button("Add to dataflow")).toBeNull();
  });

  it("passes the catalog row to onInstall when updating, not the stale local one", () => {
    // Installing the local row would reinstall the version already present.
    const onInstall = jest.fn();
    const catalogRow = pkg({ version: "2.0.0" });
    renderCard({ isInstalled: true, hasUpdate: true, catalogRow, onInstall });
    fireEvent.click(button("Update")!);
    expect(onInstall).toHaveBeenCalledWith(catalogRow);
  });

  it("disables its actions while the drawer is busy", () => {
    renderCard({ busy: true });
    expect(button("Add to dataflow")!.hasAttribute("disabled")).toBe(true);
  });
});

describe("PackageCard — curio.builtin", () => {
  const builtin = pkg({
    dirName: "curio.builtin@1",
    packageId: "curio.builtin",
    name: "Curio Built-in Nodes",
    readOnly: true,
  });

  it("offers no buttons at all", () => {
    render(
      <PackageCard
        {...(base as never)}
        pkg={builtin}
        isInstalled
        onUninstall={jest.fn()}
        onUnpublish={jest.fn()}
        onPublish={jest.fn()}
        catalogPublishAllowed
      />,
    );
    // Not uninstallable (the backend refuses) and not authorable (readOnly), so
    // every affordance must be suppressed.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

describe("PackageCard — author actions", () => {
  it("hides Unpublish on a read-only package even when publishing is allowed", () => {
    renderCard({
      pkg: pkg({ readOnly: true }),
      isInstalled: true,
      catalogPublishAllowed: true,
      onUninstall: jest.fn(),
      onUnpublish: jest.fn(),
    });
    expect(button("Unpublish")).toBeNull();
    // Uninstall is a lockfile operation, so readOnly does not gate it.
    expect(button("Remove from dataflow")).toBeTruthy();
  });

  it("shows Unpublish on an authorable package when publishing is allowed", () => {
    renderCard({
      isInstalled: true,
      catalogPublishAllowed: true,
      onUninstall: jest.fn(),
      onUnpublish: jest.fn(),
    });
    expect(button("Unpublish")).toBeTruthy();
  });

  it("hides Unpublish when the server forbids catalog writes", () => {
    renderCard({
      isInstalled: true,
      catalogPublishAllowed: false,
      onUninstall: jest.fn(),
      onUnpublish: jest.fn(),
    });
    expect(button("Unpublish")).toBeNull();
  });

  it("hides Remove from dataflow when no handler is supplied", () => {
    // The drawer omits onUninstall for an unsaved dataflow (no project id yet).
    renderCard({ isInstalled: true });
    expect(button("Remove from dataflow")).toBeNull();
  });
});
