import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// packagesApi re-exports refreshPackageRegistry, which drags in the registry ->
// adapters -> vega chain that will not load under jsdom.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));
jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    listLibraries: jest.fn(),
    addLibrary: jest.fn(),
    removeLibrary: jest.fn(),
  },
}));

import LibraryManagerWindow from "../../components/menus/libraries/LibraryManagerWindow";
import { packagesApi } from "../../api/packagesApi";

/**
 * The Installed-libraries modal had no test at all.
 *
 * Its interesting logic is entirely about *reporting truthfully* while pip runs
 * synchronously on the server:
 *
 *   - "Installed" vs "Already installed" is derived from the response's
 *     `installed`/`skipped` arrays. Getting that backwards tells the user work
 *     happened when none did (or vice versa).
 *   - Package-declared libraries are read-only here: offering Remove on one
 *     would imply the user can drop a dependency their installed package needs.
 *   - JS add is refused before it is sent (#239): the backend answers 501, so
 *     an enabled Add could only ever produce a red "Failed" row for an
 *     operation the dialog itself invited. If one is somehow sent anyway, the
 *     row must NOT be persisted optimistically.
 */

const mockList = packagesApi.listLibraries as jest.Mock;
const mockAdd = packagesApi.addLibrary as jest.Mock;
const mockRemove = packagesApi.removeLibrary as jest.Mock;

const listing = (
  standalone: { python?: string[]; js?: string[] } = {},
  fromPackages: unknown[] = [],
) => ({
  standalone: { python: standalone.python ?? [], js: standalone.js ?? [] },
  fromPackages,
});

const open = () => render(<LibraryManagerWindow open closeModal={jest.fn()} />);

const specInput = () =>
  document.querySelector('input[type="text"]') as HTMLInputElement;

const kindSelect = () =>
  document.querySelector("select") as HTMLSelectElement;

const addButton = () => screen.getByRole("button", { name: "Add" });

beforeEach(() => {
  jest.clearAllMocks();
  mockList.mockResolvedValue(listing());
  mockAdd.mockResolvedValue({
    standalone: { python: ["numpy"], js: [] },
    installed: ["numpy"],
    skipped: [],
  });
  mockRemove.mockResolvedValue({ standalone: { python: [], js: [] } });
});

describe("LibraryManagerWindow - rendering", () => {
  it("renders nothing until opened", () => {
    render(<LibraryManagerWindow open={false} closeModal={jest.fn()} />);
    expect(screen.queryByRole("heading", { name: "Installed libraries" })).toBeNull();
    expect(mockList).not.toHaveBeenCalled();
  });

  it("loads the list on open", async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "Installed libraries" })).toBeTruthy();
  });

  it("shows an empty state when nothing is installed", async () => {
    open();
    expect(await screen.findByText("No libraries installed.")).toBeTruthy();
  });

  it("lists a standalone library with a Remove control", async () => {
    mockList.mockResolvedValue(listing({ python: ["numpy"] }));
    open();
    expect(await screen.findByText("numpy")).toBeTruthy();
    expect(screen.getByTitle("Remove from your library list")).toBeTruthy();
  });

  it("offers no Remove for a package-declared library", async () => {
    // Dropping it here would strip a dependency the parent package needs; the
    // only way out is uninstalling that package.
    mockList.mockResolvedValue(
      listing({}, [
        { name: "rasterio", spec: ">=1.3", kind: "python", source: "curio.weather@1", installed: true },
      ]),
    );
    open();
    expect(await screen.findByText("rasterio")).toBeTruthy();
    expect(screen.queryByTitle("Remove from your library list")).toBeNull();
  });

  it("flags a declared library that is not actually importable", async () => {
    mockList.mockResolvedValue(
      listing({}, [
        { name: "ghostlib", spec: "", kind: "python", source: "me.demo@1", installed: false },
      ]),
    );
    open();
    expect(await screen.findByText("not installed")).toBeTruthy();
  });
});

describe("LibraryManagerWindow - adding", () => {
  it("keeps Add disabled until a spec is typed", async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    const add = screen.getByRole("button", { name: "Add" });
    expect(add.hasAttribute("disabled")).toBe(true);
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    expect(add.hasAttribute("disabled")).toBe(false);
  });

  it("posts the selected kind and spec, then clears the input", async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(mockAdd).toHaveBeenCalledWith("python", "numpy"));
    // Cleared immediately so a second spec can be queued while pip runs.
    await waitFor(() => expect(specInput().value).toBe(""));
  });

  it("reports a real install as Installed", async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("✓ Installed", {}, { timeout: 3000 })).toBeTruthy();
  });

  it("reports a no-op as Already installed", async () => {
    // Nothing was fetched: everything came back under `skipped`.
    mockAdd.mockResolvedValue({
      standalone: { python: ["numpy"], js: [] },
      installed: [],
      skipped: ["numpy"],
    });
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(
      await screen.findByText("✓ Already installed", {}, { timeout: 3000 }),
    ).toBeTruthy();
  });

  it("renders the new row from the response alone, without re-listing", async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("numpy")).toBeTruthy();
    // handleAdd deliberately never calls reload().
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it("surfaces a failed install and persists no row", async () => {
    mockAdd.mockRejectedValue(
      new Error("JS library install is not yet supported; declare in a node package's manifest instead"),
    );
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(specInput(), { target: { value: "lodash" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(
      await screen.findByText(/Couldn't install lodash/, {}, { timeout: 3000 }),
    ).toBeTruthy();
    expect(screen.getByText(/not yet supported/)).toBeTruthy();
    // The optimistic row is dropped, not left behind as if it had worked.
    expect(screen.queryByTitle("Remove from your library list")).toBeNull();
  });
});

describe("LibraryManagerWindow - removing", () => {
  it("sends the kind and spec to the delete endpoint", async () => {
    mockList.mockResolvedValue(listing({ python: ["numpy"] }));
    open();
    await screen.findByText("numpy");
    fireEvent.click(screen.getByTitle("Remove from your library list"));
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("python", "numpy"));
  });
});

/**
 * #239: the dialog marked JavaScript "coming soon" and then enabled Add anyway.
 *
 * The backend has always answered 501, so the only thing an enabled Add could
 * produce was a red "Failed" row for something the dialog had just offered.
 * The refusal belongs where the user makes the choice, not two round trips
 * later. The JavaScript option itself stays in the picker: package-declared JS
 * libraries are listed below, so removing the kind would make that column
 * meaningless.
 */
describe("LibraryManagerWindow - the JavaScript kind", () => {
  const selectJs = async () => {
    open();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    fireEvent.change(kindSelect(), { target: { value: "js" } });
  };

  it("is still offered, because package-declared JS libraries are listed", async () => {
    await selectJs();
    expect(kindSelect().value).toBe("js");
    expect(
      Array.from(kindSelect().options).map((o) => o.value),
    ).toEqual(["python", "js"]);
  });

  it("disables the spec box and Add", async () => {
    await selectJs();
    expect(specInput().hasAttribute("disabled")).toBe(true);
    expect(addButton().hasAttribute("disabled")).toBe(true);
  });

  it("explains where a JavaScript dependency does belong", async () => {
    await selectJs();
    expect(screen.getByText(/cannot install JavaScript libraries/i)).toBeTruthy();
    expect(screen.getByText("dependencies.js")).toBeTruthy();
    expect(screen.getByText("manifest.json")).toBeTruthy();
  });

  it("points the disabled box at that explanation for a screen reader", async () => {
    // Otherwise the control is simply dead with no announced reason.
    await selectJs();
    const described = specInput().getAttribute("aria-describedby");
    expect(described).toBeTruthy();
    expect(document.getElementById(described as string)).not.toBeNull();
  });

  it("drops the coming-soon placeholder that invited the attempt", async () => {
    await selectJs();
    expect(specInput().placeholder).not.toMatch(/coming soon/i);
  });

  it("sends nothing, even when Enter is pressed in the box", async () => {
    // The button being disabled does not stop the keydown handler, so the
    // guard in handleAdd is what this pins.
    await selectJs();
    fireEvent.change(specInput(), { target: { value: "lodash@^4.17" } });
    fireEvent.keyDown(specInput(), { key: "Enter" });
    fireEvent.click(addButton());
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    expect(mockAdd).not.toHaveBeenCalled();
  });

  it("re-enables both controls on the way back to Python", async () => {
    await selectJs();
    fireEvent.change(kindSelect(), { target: { value: "python" } });
    expect(specInput().hasAttribute("disabled")).toBe(false);
    fireEvent.change(specInput(), { target: { value: "numpy" } });
    expect(addButton().hasAttribute("disabled")).toBe(false);
    fireEvent.click(addButton());
    await waitFor(() => expect(mockAdd).toHaveBeenCalledWith("python", "numpy"));
  });
});
