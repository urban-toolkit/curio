import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * The last step of making a package: publisher, license, permissions and README
 * are typed here and nowhere else, and this modal had no test at any layer.
 *
 * ``test_package_metadata_roundtrip_e2e.py`` proves these fields survive an
 * export and re-import. What it cannot see is the *shaping* on the way out -
 * the PATCH body is assembled from seven pieces of local state with three
 * different emptiness rules, and a wrong rule looks identical in the browser
 * until the value reaches disk. That shaping is what this file pins.
 */

const mockListInstalled = jest.fn();
const mockUpdatePackageMetadata = jest.fn();
const mockRefreshPackageRegistry = jest.fn();
const mockShowToast = jest.fn();

jest.mock("../../api/packagesApi", () => ({
  packagesApi: {
    listInstalled: (...a: unknown[]) => mockListInstalled(...a),
    updatePackageMetadata: (...a: unknown[]) => mockUpdatePackageMetadata(...a),
  },
  refreshPackageRegistry: (...a: unknown[]) => mockRefreshPackageRegistry(...a),
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

import { PackageMetadataModal } from "../../components/packages/editing/PackageMetadataModal";

const DIR = "acme.demo@1";

const installed = (over: Record<string, any> = {}) => ({
  dirName: DIR,
  packageId: "acme.demo",
  major: 1,
  version: "0.1.0",
  name: "Demo Package",
  description: "A demo",
  publisher: "Acme",
  license: "MIT",
  readme: "# Demo\n",
  permissions: ["filesystem.read"],
  dependencies: { packages: {}, python: {}, js: {} },
  templates: [],
  ...over,
});

async function renderModal(over: Record<string, any> = {}) {
  const onClose = jest.fn();
  const onSaved = jest.fn();
  render(<PackageMetadataModal dirName={DIR} onClose={onClose} onSaved={onSaved} />);
  // The form is rendered only after GET /api/packages resolves.
  await screen.findByLabelText("Publisher");
  return { onClose, onSaved };
}

const body = () => mockUpdatePackageMetadata.mock.calls[0][1];

beforeEach(() => {
  mockListInstalled.mockReset();
  mockUpdatePackageMetadata.mockReset();
  mockRefreshPackageRegistry.mockReset();
  mockShowToast.mockReset();
  mockListInstalled.mockResolvedValue({ packages: [installed()] });
  mockUpdatePackageMetadata.mockResolvedValue({ package: installed() });
  mockRefreshPackageRegistry.mockResolvedValue(undefined);
});

describe("PackageMetadataModal - loading", () => {
  test("pre-populates every field from the installed payload", async () => {
    await renderModal();
    expect(screen.getByLabelText("Name")).toHaveValue("Demo Package");
    expect(screen.getByLabelText("Description")).toHaveValue("A demo");
    expect(screen.getByLabelText("Publisher")).toHaveValue("Acme");
    expect(screen.getByLabelText("License")).toHaveValue("MIT");
    expect(screen.getByLabelText("README")).toHaveValue("# Demo\n");
    // Stored as a list, edited as a comma-separated string.
    expect(screen.getByLabelText(/Permissions/)).toHaveValue("filesystem.read");
  });

  test("the runtime range opens blank even though the package has one", async () => {
    // Not a bug to fix here, a contract to record: curioRuntime is not carried
    // on PackagePayload, so the field is write-only. The e2e round trip
    // deliberately does not assert it comes back, and this is why.
    await renderModal();
    expect(screen.getByLabelText(/Curio runtime range/)).toHaveValue("");
  });

  test("a package that is gone renders an alert instead of a form", async () => {
    mockListInstalled.mockResolvedValue({ packages: [] });
    render(<PackageMetadataModal dirName={DIR} onClose={jest.fn()} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Package "${DIR}" is no longer installed.`);
    expect(screen.queryByLabelText("Publisher")).toBeNull();
  });

  test("auto-detected dependencies are shown read-only", async () => {
    mockListInstalled.mockResolvedValue({
      packages: [
        installed({ dependencies: { packages: {}, python: { pandas: "*" }, js: {} } }),
      ],
    });
    render(<PackageMetadataModal dirName={DIR} onClose={jest.fn()} />);
    expect(await screen.findByText(/python: pandas/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Dependencies/)).toBeNull();
  });
});

describe("PackageMetadataModal - PATCH body shaping", () => {
  test("splits permissions on commas and drops the blanks", async () => {
    await renderModal();
    fireEvent.change(screen.getByLabelText(/Permissions/), {
      target: { value: "filesystem.read, network.fetch ,, " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(mockUpdatePackageMetadata.mock.calls[0][0]).toBe(DIR);
    expect(body().permissions).toEqual(["filesystem.read", "network.fetch"]);
  });

  test("a cleared license is sent as null, not an empty string", async () => {
    // The manifest models "no license" as null; "" would fail validation.
    await renderModal();
    fireEvent.change(screen.getByLabelText("License"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(body().license).toBeNull();
  });

  test("a cleared name is omitted rather than blanking the package", async () => {
    await renderModal();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(body().name).toBeUndefined();
  });

  test("compatibility is omitted when the runtime field is left blank", async () => {
    // It always opens blank, so sending it unconditionally would wipe the
    // package's real curioRuntime on every unrelated metadata edit.
    await renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(body()).not.toHaveProperty("compatibility");
  });

  test("compatibility is sent when the runtime field is filled", async () => {
    await renderModal();
    fireEvent.change(screen.getByLabelText(/Curio runtime range/), {
      target: { value: " >=0.5.0 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(body().compatibility).toEqual({ curioRuntime: ">=0.5.0" });
  });

  test("the README is sent verbatim, whitespace included", async () => {
    await renderModal();
    fireEvent.change(screen.getByLabelText("README"), {
      target: { value: "# Title\n\nBody text.\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(mockUpdatePackageMetadata).toHaveBeenCalled());
    expect(body().readme).toBe("# Title\n\nBody text.\n");
  });
});

describe("PackageMetadataModal - save outcome", () => {
  test("a successful save refreshes the registry, toasts and closes", async () => {
    mockUpdatePackageMetadata.mockResolvedValue({
      package: installed({ name: "Renamed" }),
    });
    const { onClose, onSaved } = await renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    // Order matters: the palette reads the registry, so refreshing after the
    // PATCH is what makes the new name visible without a reload.
    expect(mockRefreshPackageRegistry).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith(
      "Metadata updated for Renamed.",
      "success",
    );
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Renamed" }),
    );
  });

  test("a rejected save surfaces the server's error and stays open", async () => {
    mockUpdatePackageMetadata.mockRejectedValue(
      Object.assign(new Error("HTTP 403"), {
        body: { error: "this package is read-only" },
      }),
    );
    const { onClose } = await renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    // The server's own message, not the generic HTTP one: "read-only" tells the
    // user what to do next, "HTTP 403" does not.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "this package is read-only",
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(mockShowToast).not.toHaveBeenCalled();
    // Still editable, so the user can retry rather than reopening the modal.
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  test("Cancel closes without patching", async () => {
    const { onClose } = await renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(mockUpdatePackageMetadata).not.toHaveBeenCalled();
  });
});
