import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { MyPackagesList } from "../../components/packages/publishing/MyPackagesList";
import type { PackagePayload } from "../../api/packagesApi";

/**
 * Covers the drawer's "Reload from catalog" action and the row-action plumbing
 * behind it.
 *
 * Reload is the authoring loop for a package you are editing under
 * ``packages/``: installing is a no-op once a copy exists in the user store, so
 * without it on-disk edits never reach the running app.
 */

const pkg = (over: Partial<PackagePayload> = {}): PackagePayload =>
  ({
    dirName: "me.demo@1",
    packageId: "me.demo",
    name: "Demo",
    version: "1.0.0",
    templates: [{ id: "me.demo/demo" }],
    lineage: null,
    familyKey: "me.demo@1",
    ...over,
  } as unknown as PackagePayload);

const reloadButton = () => screen.queryByLabelText(/Reload .* from catalog/);

describe("MyPackagesList — reload from catalog", () => {
  test("offers Reload when the catalog carries the package", () => {
    const installed = pkg();
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map([[installed.dirName, installed]])}
        onReloadFromCatalog={jest.fn()}
      />,
    );
    expect(reloadButton()).not.toBeNull();
  });

  test("offers Reload even when the version is unchanged", () => {
    // The common authoring case: source edited, `version` left alone. The old
    // `hasUpdate` signal would miss this entirely.
    const installed = pkg({ version: "1.0.0" });
    const catalogCopy = pkg({ version: "1.0.0" });
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map([[installed.dirName, catalogCopy]])}
        onReloadFromCatalog={jest.fn()}
      />,
    );
    expect(reloadButton()).not.toBeNull();
  });

  test("hides Reload for a package the catalog does not carry", () => {
    const installed = pkg();
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map()}
        onReloadFromCatalog={jest.fn()}
      />,
    );
    expect(reloadButton()).toBeNull();
  });

  test("hides Reload for a read-only package", () => {
    const installed = pkg({ readOnly: true });
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map([[installed.dirName, installed]])}
        onReloadFromCatalog={jest.fn()}
      />,
    );
    expect(reloadButton()).toBeNull();
  });

  test("clicking Reload passes the package back", () => {
    const installed = pkg();
    const onReloadFromCatalog = jest.fn();
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map([[installed.dirName, installed]])}
        onReloadFromCatalog={onReloadFromCatalog}
      />,
    );
    fireEvent.click(reloadButton()!);
    expect(onReloadFromCatalog).toHaveBeenCalledWith(
      expect.objectContaining({ dirName: "me.demo@1" }),
    );
  });

  test("the reloading row disables its button", () => {
    const installed = pkg();
    render(
      <MyPackagesList
        installed={[installed]}
        catalogByDir={new Map([[installed.dirName, installed]])}
        reloadingPackageKey={installed.dirName}
        onReloadFromCatalog={jest.fn()}
      />,
    );
    expect(reloadButton()).toBeDisabled();
  });
});

describe("MyPackagesList — fork family header actions", () => {
  /**
   * Regression: the family-header action props used to pass ``package:`` while
   * ``PackageRowActions`` destructures ``pkg``, so the header rendered with
   * ``pkg === undefined`` and threw on ``pkg.dirName``. Type checking missed it
   * because the build runs through babel, not tsc.
   */
  const lineage = (fork: string, root: string) => ({
    forkedFrom: { packageId: fork, major: 1 },
    root: { packageId: root, major: 1 },
  });

  const family = [
    pkg({
      dirName: "me.root@1",
      packageId: "me.root",
      name: "Root",
      lineage: lineage("me.root", "me.root") as never,
      familyKey: "me.root@1",
    }),
    pkg({
      dirName: "me.forked@1",
      packageId: "me.forked",
      name: "Forked",
      lineage: lineage("me.root", "me.root") as never,
      familyKey: "me.root@1",
    }),
  ];

  test("renders a fork family with publish actions without throwing", () => {
    let container: HTMLElement | undefined;
    expect(() => {
      container = render(
        <MyPackagesList
          installed={family}
          catalogByDir={new Map(family.map((p) => [p.dirName, p]))}
          catalogPublishedDirs={new Set(["me.root@1"])}
          catalogPublishAllowed
          onPublishToCatalog={jest.fn()}
          onReloadFromCatalog={jest.fn()}
        />,
      ).container;
    }).not.toThrow();

    // Guard the guard: this fixture must actually take the family-accordion
    // branch, otherwise the regression above would go untested.
    expect(container!.querySelector("details summary")).not.toBeNull();
    expect(screen.getByText("Forked")).toBeInTheDocument();
  });

  test("the family header's Reload targets the root package", () => {
    const onReloadFromCatalog = jest.fn();
    render(
      <MyPackagesList
        installed={family}
        catalogByDir={new Map(family.map((p) => [p.dirName, p]))}
        onReloadFromCatalog={onReloadFromCatalog}
      />,
    );
    // Header row + the nested root row both expose one; the first is the header.
    const buttons = screen.getAllByLabelText(/Reload Root from catalog/);
    fireEvent.click(buttons[0]);
    expect(onReloadFromCatalog).toHaveBeenCalledWith(
      expect.objectContaining({ dirName: "me.root@1" }),
    );
  });
});
