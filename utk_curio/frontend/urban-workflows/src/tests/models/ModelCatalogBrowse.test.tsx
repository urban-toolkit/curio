/**
 * The Model Catalog page, `/catalog/models`: the Node Catalog page's code,
 * listing the model packages (kind `model`) through the same services, with
 * the same rail, header import, side drawer, Add to all projects and details
 * modal. The modal shows the model's fields, its code's and its weights'
 * licenses, the node a drop creates and the package's modules. The Node
 * Catalog page lists no model package.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ModelCatalogBrowse } from "../../pages/models/ModelCatalogBrowse";
import { NodeCatalogBrowse } from "../../pages/catalog/NodeCatalogBrowse";
import {
  builtinPackage,
  ddrnetPackage,
  deepUmbraPackage,
  importedModelPackage,
  scoutPackage,
} from "../_support/modelPackages";

const mockApi = {
  catalog: jest.fn(),
  listInstalled: jest.fn(),
  factoryCapabilities: jest.fn(),
  getDefaults: jest.fn(),
  resolve: jest.fn(),
  installToDefaults: jest.fn(),
  weightsLicense: jest.fn(),
  download: jest.fn(),
  uploadArchive: jest.fn(),
  uninstall: jest.fn(),
};
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: new Proxy({}, { get: (_target, name: string) => (mockApi as any)[name] }),
}));
jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn().mockResolvedValue({ items: [] }),
  getToken: jest.fn(() => "token"),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));

let location = "";
const LocationProbe: React.FC = () => {
  location = useLocation().pathname;
  return null;
};

function renderPage(entry = "/catalog/models") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/catalog/models/:modelId?" element={<ModelCatalogBrowse />} />
        <Route path="/catalog/nodes" element={<NodeCatalogBrowse />} />
        <Route path="/catalog/discovery/:sourceDir" element={<div>source page</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

/** The grid card for one package. Scoped, because a runtime or a type label
 *  appears on the rail and the card alike. */
function card(dirName: string): HTMLElement | null {
  return document.querySelector(`.cardGrid article[data-pkg-dir="${dirName}"]`);
}

async function gridCard(dirName: string): Promise<HTMLElement> {
  await waitFor(() => expect(card(dirName)).not.toBeNull());
  return card(dirName)!;
}

function railRow(name: RegExp): HTMLElement {
  const rail = screen.getByRole("complementary", { name: "Filter models" });
  return within(rail).getByRole("button", { name });
}

const details = () => screen.queryByRole("dialog", { name: "Model details" });

beforeEach(() => {
  jest.clearAllMocks();
  location = "";
  mockApi.catalog.mockResolvedValue({
    packages: [ddrnetPackage(), deepUmbraPackage(), builtinPackage(), scoutPackage()],
    families: [],
    catalogCollisions: [],
  });
  mockApi.listInstalled.mockResolvedValue({
    packages: [ddrnetPackage(), builtinPackage(), importedModelPackage()],
  });
  mockApi.factoryCapabilities.mockResolvedValue({ catalogPublish: false });
  mockApi.getDefaults.mockResolvedValue({ packages: [] });
  mockApi.resolve.mockResolvedValue({ lockfile: [], conflicts: [] });
  mockApi.installToDefaults.mockResolvedValue({ projects: [{ id: "p1", ok: true }] });
  mockApi.weightsLicense.mockResolvedValue("MIT License\n\nCityscapes terms of use.");
  mockApi.download.mockResolvedValue(undefined);
  mockApi.uninstall.mockResolvedValue(undefined);
});

describe("the Model Catalog page", () => {
  test("lists the model packages, the catalog's and the account's own, and no node package", async () => {
    renderPage();
    await gridCard("model.curio.ddrnet23-slim@1");
    expect(card("model.scout.deep-umbra@1")).not.toBeNull();
    expect(card("imported.xabc123def456@1")).not.toBeNull();
    expect(card("curio.builtin@1")).toBeNull();
    expect(card("curio.scout@1")).toBeNull();
    expect(screen.getByRole("heading", { name: /Model Catalog/ })).toBeInTheDocument();
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { apiFetch } = require("../../utils/authApi");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  test("a card shows the name, publisher, runtime, label count, size and the weights' license", async () => {
    renderPage();
    const ddrnet = await gridCard("model.curio.ddrnet23-slim@1");
    expect(ddrnet).toHaveTextContent("DDRNet23-Slim (street scenes)");
    expect(ddrnet).toHaveTextContent("Curio");
    expect(ddrnet).toHaveTextContent("ONNX");
    expect(ddrnet).toHaveTextContent("19 labels");
    expect(ddrnet).toHaveTextContent("22.0 MB");
    expect(ddrnet).toHaveTextContent("MIT; trained on Cityscapes");
    expect(card("model.scout.deep-umbra@1")).toHaveTextContent("Used with the permission of SCOUT's authors");
  });

  test("the rail narrows the grid by type and by runtime", async () => {
    renderPage();
    await gridCard("model.curio.ddrnet23-slim@1");
    expect(railRow(/All models/)).toHaveTextContent("3");
    fireEvent.click(railRow(/Image to image/));
    await waitFor(() => expect(card("model.curio.ddrnet23-slim@1")).toBeNull());
    expect(card("model.scout.deep-umbra@1")).not.toBeNull();
    fireEvent.click(railRow(/Image to image/));
    fireEvent.click(railRow(/Transformers/));
    await waitFor(() => expect(card("model.scout.deep-umbra@1")).toBeNull());
    expect(card("imported.xabc123def456@1")).not.toBeNull();
  });

  test("the search narrows the grid", async () => {
    renderPage();
    await gridCard("model.curio.ddrnet23-slim@1");
    fireEvent.change(screen.getByPlaceholderText("Search models…"), { target: { value: "shadow" } });
    await waitFor(() => expect(card("model.curio.ddrnet23-slim@1")).toBeNull());
    expect(card("model.scout.deep-umbra@1")).not.toBeNull();
  });

  test("the side drawer opens on the first model, and Add to all projects reviews then adds it", async () => {
    renderPage();
    await gridCard("model.curio.ddrnet23-slim@1");
    fireEvent.click(card("model.scout.deep-umbra@1")!);
    const add = await screen.findByRole("button", { name: "Add to all projects" });
    fireEvent.click(add);
    const review = await screen.findByRole("dialog", { name: "" });
    expect(review).toHaveTextContent('Add "Deep Umbra (accumulated shadows)"');
    await act(async () => {
      fireEvent.click(within(review).getByRole("button", { name: "Add to all projects" }));
    });
    await waitFor(() => expect(mockApi.installToDefaults).toHaveBeenCalledWith("model.scout.deep-umbra@1"));
  });

  test("the header imports a package archive", async () => {
    renderPage();
    await gridCard("model.curio.ddrnet23-slim@1");
    expect(screen.getByRole("button", { name: /Import package/ })).toBeInTheDocument();
  });

  test("View details shows the model's fields, both licenses, the node a drop creates and its modules", async () => {
    renderPage();
    const deepUmbra = await gridCard("model.scout.deep-umbra@1");
    fireEvent.click(within(deepUmbra).getByRole("button", { name: "View details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    const row = (label: string) => {
      const term = within(modal).getByText(label, { selector: "dt" });
      return term.nextElementSibling as HTMLElement;
    };
    expect(row("Type")).toHaveTextContent("Image to image");
    expect(row("Runtime")).toHaveTextContent("ONNX");
    expect(row("Input size")).toHaveTextContent("512 × 512, float32");
    expect(row("Size")).toHaveTextContent("10.0 MB");
    expect(row("Code license")).toHaveTextContent("MIT");
    expect(row("Weights license")).toHaveTextContent("Used with the permission of SCOUT's authors");
    expect(row("Node")).toHaveTextContent("Accumulated Shadow");
    // A pip install has not fetched its weights yet.
    expect(row("Weights")).toHaveTextContent("Downloads on first use");
    expect(within(modal).getByRole("heading", { name: /Modules/ })).toBeInTheDocument();
    expect(modal).toHaveTextContent("deep_umbra");
    // Same export as every package.
    expect(within(modal).getByRole("button", { name: "Export" })).toBeInTheDocument();
  });

  test("a model's labels show as chips, and its weights' license text opens in the details", async () => {
    renderPage();
    const ddrnet = await gridCard("model.curio.ddrnet23-slim@1");
    fireEvent.click(within(ddrnet).getByRole("button", { name: "View details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    expect(within(modal).getByText("Labels", { selector: "dt" }).nextElementSibling).toHaveTextContent("19");
    expect(modal.querySelector('[data-curio-model-labels="true"]')).toHaveTextContent("sidewalk");
    // Weights at hand: nothing to download.
    expect(within(modal).queryByText("Downloads on first use")).toBeNull();
    await act(async () => {
      fireEvent.click(within(modal).getByRole("button", { name: "View license" }));
    });
    await waitFor(() => expect(mockApi.weightsLicense).toHaveBeenCalledWith("model.curio.ddrnet23-slim@1"));
    expect(modal.querySelector('[data-curio-model-license="true"]')).toHaveTextContent("Cityscapes terms of use.");
  });

  test("a downloaded model says where it came from, and links there", async () => {
    renderPage();
    const segformer = await gridCard("imported.xabc123def456@1");
    fireEvent.click(within(segformer).getByRole("button", { name: "View details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    fireEvent.click(within(modal).getByRole("link", { name: /Hugging Face/ }));
    await waitFor(() => expect(location).toBe("/catalog/discovery/source.curio.huggingface"));
  });

  test("a link to a model opens the page with its details, and closing leaves the plain page", async () => {
    renderPage("/catalog/models/model.curio.ddrnet23-slim");
    await waitFor(() => expect(details()).toBeInTheDocument());
    expect(details()).toHaveTextContent("DDRNet23-Slim (street scenes)");
    fireEvent.click(within(details() as HTMLElement).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(details()).toBeNull());
    expect(location).toBe("/catalog/models");
  });

  test("a link to a model that is not there says so", async () => {
    renderPage("/catalog/models/model.example.none");
    expect(await screen.findByText("This model is not in your Model Catalog.")).toBeInTheDocument();
  });

  test("there is no Delete: a model leaves the account as a node package does", async () => {
    renderPage();
    const segformer = await gridCard("imported.xabc123def456@1");
    fireEvent.click(segformer);
    fireEvent.contextMenu(segformer);
    const menu = await screen.findByRole("menu", { name: "Package actions" });
    expect(within(menu).getByRole("menuitem", { name: /View details/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: /Delete/ })).toBeNull();
  });
});

describe("the Node Catalog page", () => {
  test("lists no model package", async () => {
    renderPage("/catalog/nodes");
    await gridCard("curio.scout@1");
    expect(card("curio.builtin@1")).not.toBeNull();
    for (const dirName of ["model.curio.ddrnet23-slim@1", "model.scout.deep-umbra@1", "imported.xabc123def456@1"]) {
      expect(card(dirName)).toBeNull();
    }
    const rail = screen.getByRole("complementary", { name: "Filter packages" });
    expect(within(rail).getByRole("button", { name: /All packages/ })).toHaveTextContent("2");
  });
});

describe("Remove from account, on both catalog pages", () => {
  /** The account's store as a page lists it: each row says whether a
   *  dataflow uses it. */
  function store(...rows: unknown[]) {
    mockApi.listInstalled.mockResolvedValue({ packages: rows });
  }

  /** The side drawer, once it describes *name*. */
  function drawerOn(name: string): Promise<HTMLElement> {
    return waitFor(() => {
      const drawer = document.querySelector<HTMLElement>('[data-curio-browse-drawer="true"]');
      expect(drawer).not.toBeNull();
      expect(within(drawer as HTMLElement).getByRole("heading", { level: 2, name })).toBeInTheDocument();
      return drawer as HTMLElement;
    });
  }

  const removeButton = (scope: HTMLElement) =>
    within(scope).queryByRole("button", { name: "Remove from account" });

  test("a model of the account's own that no dataflow uses leaves the account, after asking", async () => {
    store(ddrnetPackage({ inUse: false }), builtinPackage({ inUse: true }), importedModelPackage({ inUse: false }));
    renderPage();
    fireEvent.click(await gridCard("imported.xabc123def456@1"));
    const drawer = await drawerOn("SegFormer B0 (ADE20K)");
    fireEvent.click(removeButton(drawer) as HTMLElement);

    const confirm = await screen.findByRole("dialog", { name: "Remove SegFormer B0 (ADE20K) from your account?" });
    expect(mockApi.uninstall).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    });
    await waitFor(() =>
      expect(mockApi.uninstall).toHaveBeenCalledWith("imported.xabc123def456@1", { unusedOnly: true }),
    );
    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith("Removed SegFormer B0 (ADE20K) from your account.", "success"),
    );
    // The page asks the store which packages a dataflow uses.
    expect(mockApi.listInstalled).toHaveBeenCalledWith(undefined, { usage: true });
  });

  test("a shipped model, and a model of the account's own that a dataflow uses, offer no Remove from account", async () => {
    store(ddrnetPackage({ inUse: false }), builtinPackage({ inUse: true }), importedModelPackage({ inUse: true }));
    renderPage();
    fireEvent.click(await gridCard("model.curio.ddrnet23-slim@1"));
    expect(removeButton(await drawerOn("DDRNet23-Slim (street scenes)"))).toBeNull();
    fireEvent.click(card("imported.xabc123def456@1")!);
    expect(removeButton(await drawerOn("SegFormer B0 (ADE20K)"))).toBeNull();
  });

  test("the Node Catalog page offers it for a node package of the account's own that no dataflow uses", async () => {
    const own = scoutPackage({
      packageId: "imported.xnodes1234567",
      dirName: "imported.xnodes1234567@1",
      name: "My raster nodes",
      inUse: false,
    });
    store(builtinPackage({ inUse: true }), own);
    renderPage("/catalog/nodes");
    fireEvent.click(await gridCard("imported.xnodes1234567@1"));
    const drawer = await drawerOn("My raster nodes");
    fireEvent.click(removeButton(drawer) as HTMLElement);

    const confirm = await screen.findByRole("dialog", { name: "Remove My raster nodes from your account?" });
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    });
    await waitFor(() =>
      expect(mockApi.uninstall).toHaveBeenCalledWith("imported.xnodes1234567@1", { unusedOnly: true }),
    );
  });
});
