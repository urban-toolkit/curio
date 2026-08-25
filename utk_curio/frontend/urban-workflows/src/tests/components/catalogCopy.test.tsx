import React from "react";
import { render, screen } from "@testing-library/react";
import { PackageSearchRow } from "../../components/packages/publishing/PackageSearchRow";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import type { PackagePayload } from "../../api/packagesApi";

/**
 * Pins the catalog's per-surface copy and the props that vary it.
 *
 * The drawer and the /catalog page do different things with the same
 * components: the drawer edits one dataflow's lockfile ("Add to dataflow")
 * while /catalog writes the user's defaults and walks every project ("Add to
 * all projects"). Both used to say "Install", which described neither. A
 * default that silently reverts is the likely regression, so the overrides are
 * asserted alongside the defaults.
 */

const pkg = (over: Partial<PackagePayload> = {}): PackagePayload =>
  ({
    dirName: "me.demo@1",
    packageId: "me.demo",
    name: "Demo",
    version: "1.0.0",
    publisher: "Me",
    permissions: [],
    dependencies: { python: {}, js: {} },
    templates: [{ id: "me.demo/demo" }],
    ...over,
  } as unknown as PackagePayload);

describe("InstallPermissionsDialog confirm label", () => {
  const renderDialog = (props: Record<string, unknown> = {}) =>
    render(
      <InstallPermissionsDialog
        pkg={pkg()}
        conflicts={[]}
        busy={false}
        onCancel={jest.fn()}
        onConfirm={jest.fn()}
        {...props}
      />,
    );

  test("defaults to the drawer's per-dataflow wording", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Add to dataflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  });

  test("the /catalog page overrides it to say all projects", () => {
    renderDialog({ confirmLabel: "Add to all projects" });
    expect(
      screen.getByRole("button", { name: "Add to all projects" }),
    ).toBeInTheDocument();
  });

  test("the busy caption replaces the label while working", () => {
    renderDialog({ busy: true, confirmLabel: "Add to all projects" });
    expect(screen.getByRole("button", { name: "Adding…" })).toBeInTheDocument();
  });

  test("the title asks to Add, not to Install", () => {
    renderDialog();
    expect(screen.getByRole("heading", { name: /Add "Demo"/ })).toBeInTheDocument();
  });
});

describe("PackageSearchRow per-surface options", () => {
  const renderRow = (props: Record<string, unknown> = {}) =>
    render(
      <PackageSearchRow
        search=""
        sort="new"
        onSearchChange={jest.fn()}
        onSortChange={jest.fn()}
        {...props}
      />,
    );

  test("defaults to package-catalog copy and options", () => {
    renderRow();
    expect(screen.getByPlaceholderText(/Search packages/)).toBeInTheDocument();
    const select = screen.getByLabelText("Sort packages") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["new", "name"]);
  });

  test("the dataset drawer supplies its own placeholder, label, and options", () => {
    // The drawer's state is "recent"|"name" but the select used to offer
    // "new"|"name", so the control rendered with no matching option.
    renderRow({
      sort: "recent",
      placeholder: "Search datasets, publishers, tags…",
      sortAriaLabel: "Sort datasets",
      sortOptions: [
        { value: "recent", label: "Sort: Recent activity" },
        { value: "name", label: "Sort: Name" },
      ],
    });
    expect(screen.getByPlaceholderText(/Search datasets/)).toBeInTheDocument();
    const select = screen.getByLabelText("Sort datasets") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["recent", "name"]);
    expect(select.value).toBe("recent");
  });

  test("every offered option is selectable, so the control is never orphaned", () => {
    const options = [
      { value: "recent", label: "Sort: Recent activity" },
      { value: "name", label: "Sort: Name" },
    ];
    for (const { value } of options) {
      const { unmount } = render(
        <PackageSearchRow
          search=""
          sort={value}
          onSearchChange={jest.fn()}
          onSortChange={jest.fn()}
          sortAriaLabel="Sort datasets"
          sortOptions={options}
        />,
      );
      expect((screen.getByLabelText("Sort datasets") as HTMLSelectElement).value).toBe(value);
      unmount();
    }
  });
});
