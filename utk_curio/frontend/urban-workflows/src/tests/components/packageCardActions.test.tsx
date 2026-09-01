import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PackageCard } from "../../components/packages/publishing/PackageCard";
import type { PackageCardProps } from "../../components/packages/publishing/PackageCard";
import type { PackagePayload } from "../../api/packagesApi";

/**
 * Which action a package card offers is a pure function of its props, and it had
 * no test - even though the labels have been renamed three times in the last
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

const renderCard = (over: Partial<PackageCardProps> = {}) =>
  render(<PackageCard {...base} pkg={pkg()} {...over} />);

const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => jest.clearAllMocks());

describe("PackageCard - primary action", () => {
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

  it("offers Update when installed with a newer catalog version", () => {
    renderCard({
      isInstalled: true,
      hasUpdate: true,
      catalogRow: pkg({ version: "2.0.0" }),
      onUninstall: jest.fn(),
    });
    expect(button("Update")).toBeTruthy();
    expect(button("Add to project")).toBeNull();
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
    expect(button("Add to project")!.hasAttribute("disabled")).toBe(true);
  });
});

describe("PackageCard - curio.builtin", () => {
  const builtin = pkg({
    dirName: "curio.builtin@1",
    packageId: "curio.builtin",
    name: "Curio Built-in Nodes",
    readOnly: true,
  });

  it("offers no ACTION buttons at all", () => {
    render(
      <PackageCard
        {...base}
        pkg={builtin}
        isInstalled
        onUninstall={jest.fn()}
        onUnpublish={jest.fn()}
        onPublish={jest.fn()}
        catalogPublishAllowed
      />,
    );
    // Not uninstallable (the backend refuses) and not authorable (readOnly), so
    // every ACTION must be suppressed. The details square is not an action -
    // it is how you read what the package contains, it is on every drawer card
    // in every catalog, and with no handler supplied it renders disabled.
    const actions = screen
      .queryAllByRole("button")
      .filter((el) => !/details$/i.test(el.getAttribute("aria-label") ?? ""));
    expect(actions).toHaveLength(0);
  });
});

describe("PackageCard - no publish control", () => {
  // The card carried Publish / Unpublish, gated on `readOnly !== true`. Both
  // the control and the gate were wrong here:
  //
  //   * the PLACE - publishing puts a package into the catalog everyone on this
  //     Curio shares, which is a decision about the package, not about the
  //     dataflow this card sits in. It lives on the Node Catalog page's detail
  //     drawer now.
  //   * the GATE - `readOnly` is an author's manifest opt-in that almost no
  //     package sets, so `readOnly !== true` matched nearly everything and put
  //     Unpublish on packages that shipped with the deployment. The drawer gates
  //     on `publishable`, which the backend computes from the publisher record
  //     and enforces on the route as well.
  it("offers no Publish, whatever the package", () => {
    renderCard({ isInstalled: true, onUninstall: jest.fn() });
    expect(button("Publish")).toBeNull();
  });

  it("offers no Unpublish, even on a published authorable package", () => {
    renderCard({ isInstalled: true, onUninstall: jest.fn() });
    expect(button("Unpublish")).toBeNull();
  });

  it("still offers the action that IS about this project", () => {
    renderCard({ isInstalled: true, onUninstall: jest.fn() });
    expect(button("Remove from project")).toBeTruthy();
  });
});
