import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { PackageSearchRow } from "../../components/packages/publishing/PackageSearchRow";
import type { DatasetSortMode } from "../../services/datasetCatalog/datasetCatalogTypes";

describe("PackageSearchRow", () => {
  it("defaults to the package sort options and copy (Nodes/Agents regression)", () => {
    render(
      <PackageSearchRow
        search=""
        sort="new"
        onSearchChange={jest.fn()}
        onSortChange={jest.fn()}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Sort packages" }) as HTMLSelectElement;
    expect(select.value).toBe("new");
    expect(
      Array.from(select.options).map((o) => [o.value, o.label]),
    ).toEqual([
      ["new", "Sort: Newest"],
      ["name", "Sort: Name"],
    ]);
    expect(
      screen.getByPlaceholderText("Search packages, publishers, tags…"),
    ).toBeInTheDocument();
  });

  it("renders custom sortOptions with a matching selection — the dataset 'recent' default is never blank (dev/74)", () => {
    render(
      <PackageSearchRow<DatasetSortMode>
        search=""
        sort="recent"
        onSearchChange={jest.fn()}
        onSortChange={jest.fn()}
        sortOptions={[
          { value: "recent", label: "Sort: Recent" },
          { value: "name", label: "Sort: Name" },
        ]}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Sort packages" }) as HTMLSelectElement;
    expect(select.value).toBe("recent");
    expect(select.selectedIndex).toBe(0);
    expect(screen.getByRole("option", { name: "Sort: Recent" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Sort: Newest" })).toBeNull();
  });

  it("reports the custom vocabulary value on change (never 'new' for datasets)", () => {
    const onSortChange = jest.fn();
    render(
      <PackageSearchRow<DatasetSortMode>
        search=""
        sort="recent"
        onSearchChange={jest.fn()}
        onSortChange={onSortChange}
        sortOptions={[
          { value: "recent", label: "Sort: Recent" },
          { value: "name", label: "Sort: Name" },
        ]}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Sort packages" }), {
      target: { value: "name" },
    });
    expect(onSortChange).toHaveBeenCalledWith("name");
  });

  it("forwards search input changes and honors copy overrides (dev/68)", () => {
    const onSearchChange = jest.fn();
    render(
      <PackageSearchRow
        search=""
        sort="new"
        onSearchChange={onSearchChange}
        onSortChange={jest.fn()}
        placeholder="Search agents, hooks, keywords..."
        sortAriaLabel="Sort agents"
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Search agents, hooks, keywords..."), {
      target: { value: "explainer" },
    });
    expect(onSearchChange).toHaveBeenCalledWith("explainer");
    expect(screen.getByRole("combobox", { name: "Sort agents" })).toBeInTheDocument();
  });
});
