import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { PackageDetailModal } from "../../components/packages/publishing/PackageDetailModal";
import type { PackagePayload } from "../../api/packagesApi";

/**
 * The Node details modal states the same status wherever it opens.
 *
 * The Node Catalog page passes it `inAllProjects` and `isPublished`; the canvas
 * drawer passed neither, and the modal defaulted both to false, so every
 * package opened from the canvas read "In all projects: No" and "Not
 * published", including the ones in every project and in the catalog.
 */

jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    getDefaults: jest.fn(),
    download: jest.fn(),
  },
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { packagesApi } = require("../../api/packagesApi") as {
  packagesApi: { getDefaults: jest.Mock };
};

const pkg = {
  packageId: "curio.examples",
  major: 1,
  version: "1.0.0",
  name: "Examples",
  publisher: "Curio",
  description: "",
  license: "MIT",
  permissions: [],
  dependencies: null,
  templates: [],
  dirName: "curio.examples@1",
  lineage: null,
  familyKey: "curio.examples@1",
  channel: "stable",
} as unknown as PackagePayload;

function statusOf(label: string): string | null {
  const dialog = screen.getByRole("dialog", { name: "Package details" });
  const term = within(dialog).queryByText(label, { selector: "dt" });
  return term ? (term.nextElementSibling?.textContent ?? null) : null;
}

beforeEach(() => {
  packagesApi.getDefaults.mockReset();
});

describe("the package details status rows", () => {
  test("say what the page tells them", () => {
    render(<PackageDetailModal pkg={pkg} inAllProjects isPublished onClose={jest.fn()} />);
    expect(statusOf("In all projects")).toBe("Yes");
    expect(statusOf("In the catalog")).toBe("Published");
    // The page already knows, so the modal does not ask again.
    expect(packagesApi.getDefaults).not.toHaveBeenCalled();
  });

  test("read the defaults list when the caller does not have it", async () => {
    packagesApi.getDefaults.mockResolvedValue({ packages: ["curio.examples@1"] });
    render(<PackageDetailModal pkg={pkg} isPublished onClose={jest.fn()} />);
    expect(await screen.findByText("Yes")).toBeInTheDocument();
    expect(statusOf("In all projects")).toBe("Yes");
  });

  test("claim nothing they do not know", () => {
    // A read that has not come back, or failed, is not a "No".
    packagesApi.getDefaults.mockReturnValue(new Promise(() => {}));
    render(<PackageDetailModal pkg={pkg} onClose={jest.fn()} />);
    expect(statusOf("In all projects")).toBeNull();
    expect(statusOf("In the catalog")).toBeNull();
  });
});

describe("the canvas drawer's details modal", () => {
  test("is told whether the package is published", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../../components/packages/publishing/NodeCatalogDrawer.tsx"),
      "utf8"
    );
    const call = src.slice(src.indexOf("<PackageDetailModal"), src.indexOf("/>", src.indexOf("<PackageDetailModal")));
    expect(call).toContain("isPublished={catalogPublishedDirs.has(detailPkg.dirName)}");
  });
});
