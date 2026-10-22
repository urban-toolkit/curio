import React from "react";
import { render, screen } from "@testing-library/react";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import type { PackagePayload } from "../../services/packages";

/**
 * The Add review lists what an add installs. Adding a package also adds each
 * package its manifest names in `dependencies.packages`, so the review lists
 * those under Dependencies, the way it lists the package's libraries.
 */

const pkg = (dependencies: Partial<PackagePayload["dependencies"]>): PackagePayload =>
  ({
    dirName: "ai.test.top@1",
    packageId: "ai.test.top",
    name: "Top",
    version: "1.0.0",
    publisher: "Tests",
    permissions: [],
    dependencies: { packages: {}, python: {}, js: {}, ...dependencies },
    templates: [{ id: "ai.test.top/caller" }],
  } as unknown as PackagePayload);

const renderReview = (payload: PackagePayload) =>
  render(
    <InstallPermissionsDialog pkg={payload} conflicts={[]} busy={false} onCancel={jest.fn()} onConfirm={jest.fn()} />,
  );

describe("the Add review's Dependencies", () => {
  test("lists each package the package names, with its range, beside its libraries", () => {
    renderReview(pkg({ packages: { "ai.test.base@1": "^1.2" }, python: { numpy: ">=1.26" } }));
    const row = screen.getByText("package · ai.test.base@1").closest("div");
    expect(row).toHaveTextContent("^1.2");
    expect(screen.getByText("python · numpy")).toBeInTheDocument();
  });

  test("lists a package that needs only packages", () => {
    renderReview(pkg({ packages: { "ai.test.base@1": "*" } }));
    expect(screen.getByText("Dependencies")).toBeInTheDocument();
    expect(screen.getByText("package · ai.test.base@1")).toBeInTheDocument();
  });

  test("lists no package for a package that names none", () => {
    renderReview(pkg({ python: { numpy: ">=1.26" } }));
    expect(screen.queryByText(/^package · /)).toBeNull();
  });
});
