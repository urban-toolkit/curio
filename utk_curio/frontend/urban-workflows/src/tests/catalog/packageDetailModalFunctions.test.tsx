/**
 * View details lists each module a package ships with the functions it
 * offers, as the header above a node's code lists them under Functions: each
 * one's call and the first paragraph of its docstring, read as the details
 * open (`GET /api/packages/<dirName>/functions`). A module of a package's
 * module folder is named under it, a module that offers nothing has no list,
 * and a read that fails leaves the modules' names.
 */
import React from "react";
import { act, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { PackageDetailModal } from "../../components/packages/publishing/PackageDetailModal";
import type { PackageFunctionsPayload, PackagePayload } from "../../services/packages";

jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    getDefaults: jest.fn(),
    download: jest.fn(),
    packageFunctions: jest.fn(),
  },
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { packagesApi } = require("../../services/packages/packagesApi") as {
  packagesApi: { packageFunctions: jest.Mock };
};

function packageOf(dirName: string, modules: string[]): PackagePayload {
  const [packageId, major] = dirName.split("@");
  return {
    packageId,
    major: Number(major),
    version: "1.0.0",
    name: packageId,
    publisher: "Curio",
    description: "",
    license: "MIT",
    permissions: [],
    dependencies: null,
    templates: [],
    dirName,
    lineage: null,
    familyKey: dirName,
    channel: "stable",
    modules,
  } as unknown as PackagePayload;
}

const DEEP_UMBRA: PackageFunctionsPayload = {
  dirName: "model.scout.deep-umbra@1",
  modules: [
    {
      module: "deep_umbra",
      problem: null,
      functions: [
        {
          name: "accumulated_shadow",
          call: "accumulated_shadow(value, season, model, output_file)",
          doc: "The accumulated shadow of the heights in *value*.",
        },
        { name: "season_factor", call: "season_factor(season)", doc: "Minutes of shadow a pixel at 1 stands for." },
      ],
    },
    { module: "deep_umbra.deep_umbra", problem: null, functions: [] },
    { module: "deep_umbra.node_outputs", problem: null, functions: [] },
  ],
};

function details(): HTMLElement {
  return screen.getByRole("dialog", { name: "Package details" });
}

beforeEach(() => {
  packagesApi.packageFunctions.mockReset();
});

test("each module with the functions it offers: each one's call and what it does", async () => {
  packagesApi.packageFunctions.mockResolvedValue(DEEP_UMBRA);
  render(
    <PackageDetailModal pkg={packageOf("model.scout.deep-umbra@1", ["deep_umbra"])} inAllProjects isPublished onClose={jest.fn()} />,
  );
  expect(within(details()).getByText("Modules (1)")).toBeInTheDocument();
  expect(await within(details()).findByText("accumulated_shadow(value, season, model, output_file)")).toBeInTheDocument();
  expect(packagesApi.packageFunctions).toHaveBeenCalledWith("model.scout.deep-umbra@1");
  const listed = Array.from(details().querySelectorAll('[data-module-functions="deep_umbra"] [data-module-function]'));
  expect(listed.map((item) => item.getAttribute("data-module-function"))).toEqual(["accumulated_shadow", "season_factor"]);
  expect(listed[1].textContent).toBe("season_factor(season)Minutes of shadow a pixel at 1 stands for.");
  // A module that offers nothing has no list.
  expect(details().querySelector('[data-module-functions="deep_umbra.deep_umbra"]')).toBeNull();
  expect(details().querySelector('[data-module-functions="deep_umbra.node_outputs"]')).toBeNull();
});

test("a module of a module folder is named under the folder", async () => {
  packagesApi.packageFunctions.mockResolvedValue({
    dirName: "curio.rasterization@1",
    modules: [
      { module: "scout_rasters", problem: null, functions: [] },
      {
        module: "scout_rasters.raster_algebra",
        problem: null,
        functions: [{ name: "raster_statistics", call: "raster_statistics(raster)", doc: "A raster's statistics." }],
      },
    ],
  });
  render(<PackageDetailModal pkg={packageOf("curio.rasterization@1", ["scout_rasters"])} inAllProjects isPublished onClose={jest.fn()} />);
  expect(await within(details()).findByText("raster_statistics(raster)")).toBeInTheDocument();
  const folder = details().querySelector('[data-package-module="scout_rasters"]')!;
  expect(within(folder as HTMLElement).getByText("scout_rasters.raster_algebra")).toBeInTheDocument();
});

test("a read that fails leaves the modules' names", async () => {
  packagesApi.packageFunctions.mockRejectedValue(new Error("HTTP 500"));
  render(<PackageDetailModal pkg={packageOf("model.scout.deep-umbra@1", ["deep_umbra"])} inAllProjects isPublished onClose={jest.fn()} />);
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
  expect(packagesApi.packageFunctions).toHaveBeenCalledWith("model.scout.deep-umbra@1");
  expect(within(details()).getByText("deep_umbra")).toBeInTheDocument();
  expect(details().querySelector("[data-module-functions]")).toBeNull();
});
