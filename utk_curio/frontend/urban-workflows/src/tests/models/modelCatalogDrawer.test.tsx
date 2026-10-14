/**
 * The canvas Model Catalog drawer: the Node Catalog drawer's code, listing the
 * model packages (kind `model`) through the same services, with the same tabs,
 * Add, Remove, Import and restart notice. The Node Catalog drawer lists none of
 * them. And a model dropped from a card onto a node.
 *
 * The drop itself is handled in `NodeContainer` (components/styles.tsx), which
 * needs the whole provider stack to render (see nodeContainerBorder.test.tsx).
 * So the two halves are checked where each lives: the drag a card starts, then
 * the same payload read back off the same DataTransfer and applied to a node's
 * data exactly as the drop handler applies it; and, from the source, that the
 * handler is wired that way.
 *
 * Code main lacks is reached through `require`, so main fails test by test.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { ModelCatalogDrawer } from "../../components/models/catalog/ModelCatalogDrawer";
import { NodeCatalogDrawer } from "../../components/packages/publishing/NodeCatalogDrawer";
import {
  builtinPackage,
  ddrnetPackage,
  deepUmbraPackage,
  importedModelPackage,
  rasterConversionPackage,
} from "../_support/modelPackages";

// The drawer reaches the node registry, whose built-in behaviors load Vega's
// ESM build: mocked virtually, as testing-gotchas prescribes.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockApi = {
  catalog: jest.fn(),
  listInstalled: jest.fn(),
  factoryCapabilities: jest.fn(),
  getProjectPackages: jest.fn(),
  getDefaults: jest.fn(),
  resolve: jest.fn(),
  installToProject: jest.fn(),
  uninstallFromProject: jest.fn(),
  uploadArchive: jest.fn(),
  weightsLicense: jest.fn(),
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
let mockLockfile: string[] = [];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    packages: mockLockfile,
    saveCurrentProject: jest.fn(),
    projectDirty: false,
  }),
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  // The node registry subscribes to the store at import.
  ...jest.requireActual("../../registry/projectPackagesStore"),
  applyProjectLockfile: jest.fn(() => false),
  getPackagesRevision: jest.fn(() => 0),
  setCurrentProjectPackages: jest.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const packages = require("../../services/packages");

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** A minimal DataTransfer: jsdom has none. */
function fakeDataTransfer() {
  const store = new Map<string, string>();
  return {
    effectAllowed: "",
    dropEffect: "",
    get types() {
      return Array.from(store.keys());
    },
    setData: (type: string, value: string) => void store.set(type, value),
    getData: (type: string) => store.get(type) ?? "",
  } as unknown as DataTransfer;
}

const MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]';
const NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]';

function renderModelDrawer() {
  return render(
    <MemoryRouter>
      <ModelCatalogDrawer presented onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
    </MemoryRouter>,
  );
}

function card(root: string, dirName: string): HTMLElement | null {
  return document.querySelector(`${root} article[data-pkg-dir="${dirName}"]`);
}

async function modelCard(dirName: string): Promise<HTMLElement> {
  await waitFor(() => expect(card(MODEL_DRAWER, dirName)).not.toBeNull());
  return card(MODEL_DRAWER, dirName)!;
}

function tab(name: "Browse all" | "In project"): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(`^${name}`) });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockLockfile = ["model.curio.ddrnet23-slim@1", "scout.raster-conversion@1"];
  // The shared catalog: two model packages and two node packages.
  mockApi.catalog.mockResolvedValue({
    packages: [ddrnetPackage(), deepUmbraPackage(), builtinPackage(), rasterConversionPackage()],
    families: [],
    catalogCollisions: [],
  });
  // The account's store: copies of what the dataflow uses, and a model
  // downloaded from the Discovery Catalog that is in the store only.
  mockApi.listInstalled.mockResolvedValue({
    packages: [ddrnetPackage(), builtinPackage(), rasterConversionPackage(), importedModelPackage()],
  });
  mockApi.factoryCapabilities.mockResolvedValue({ catalogPublish: true });
  mockApi.getProjectPackages.mockResolvedValue({ packages: mockLockfile });
  mockApi.getDefaults.mockResolvedValue({ packages: [] });
  mockApi.resolve.mockResolvedValue({ lockfile: [], conflicts: [] });
  mockApi.installToProject.mockResolvedValue({ packages: [...mockLockfile, "model.scout.deep-umbra@1"] });
  mockApi.uninstallFromProject.mockResolvedValue({ packages: ["scout.raster-conversion@1"] });
  mockApi.uploadArchive.mockResolvedValue({ package: importedModelPackage() });
  mockApi.weightsLicense.mockResolvedValue("MIT License\n\nCityscapes terms.");
});

afterEach(() => packages.endModelDrag?.());

describe("the canvas Model Catalog drawer", () => {
  test("is its own dialog, with the Node Catalog drawer's tabs", async () => {
    renderModelDrawer();
    expect(await screen.findByRole("dialog", { name: "Model Catalog" })).toBeInTheDocument();
    expect(tab("Browse all")).toBeInTheDocument();
    expect(tab("In project")).toBeInTheDocument();
  });

  test("Browse all lists the model packages, the catalog's and the account's own, and no node package", async () => {
    renderModelDrawer();
    await modelCard("model.curio.ddrnet23-slim@1");
    expect(card(MODEL_DRAWER, "model.scout.deep-umbra@1")).not.toBeNull();
    // Downloaded from the Discovery Catalog: in the store, not the catalog.
    expect(card(MODEL_DRAWER, "imported.xabc123def456@1")).not.toBeNull();
    expect(card(MODEL_DRAWER, "curio.builtin@1")).toBeNull();
    expect(card(MODEL_DRAWER, "scout.raster-conversion@1")).toBeNull();
    // Through the packages service, filtered to kind model: never /api/models.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { apiFetch } = require("../../utils/authApi");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  test("a card shows the model's runtime, labels, size and its weights' license", async () => {
    renderModelDrawer();
    const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
    expect(ddrnet).toHaveTextContent("ONNX");
    expect(ddrnet).toHaveTextContent("19 labels");
    expect(ddrnet).toHaveTextContent("22.0 MB");
    expect(ddrnet).toHaveTextContent("MIT; trained on Cityscapes");
    const deepUmbra = card(MODEL_DRAWER, "model.scout.deep-umbra@1")!;
    expect(deepUmbra).toHaveTextContent("Image to image");
    expect(deepUmbra).toHaveTextContent("Used with the permission of SCOUT's authors");
  });

  test("In project lists the dataflow's model packages and counts only them", async () => {
    renderModelDrawer();
    await modelCard("model.curio.ddrnet23-slim@1");
    // The lockfile names DDRNet and a node package; only DDRNet counts here.
    expect(tab("In project")).toHaveTextContent(/^In project1$/);
    fireEvent.click(tab("In project"));
    await waitFor(() => expect(card(MODEL_DRAWER, "model.scout.deep-umbra@1")).toBeNull());
    expect(card(MODEL_DRAWER, "model.curio.ddrnet23-slim@1")).not.toBeNull();
    expect(card(MODEL_DRAWER, "scout.raster-conversion@1")).toBeNull();
    expect(card(MODEL_DRAWER, "imported.xabc123def456@1")).toBeNull();
  });

  test("Add reviews the model against the whole store, then adds it to the dataflow", async () => {
    renderModelDrawer();
    const deepUmbra = await modelCard("model.scout.deep-umbra@1");
    fireEvent.click(within(deepUmbra).getByRole("button", { name: "Add to project" }));
    // The review resolves every package in the store, node packages included.
    await waitFor(() => expect(mockApi.resolve).toHaveBeenCalled());
    expect([...mockApi.resolve.mock.calls[0][0]].sort()).toEqual([
      "curio.builtin@1",
      "imported.xabc123def456@1",
      "model.curio.ddrnet23-slim@1",
      "model.scout.deep-umbra@1",
      "scout.raster-conversion@1",
    ]);
    const review = await screen.findByRole("dialog", { name: "" });
    expect(review).toHaveTextContent('Add "Deep Umbra (accumulated shadows)"');
    await act(async () => {
      fireEvent.click(within(review).getByRole("button", { name: "Add to project" }));
    });
    await waitFor(() =>
      expect(mockApi.installToProject).toHaveBeenCalledWith("p1", "model.scout.deep-umbra@1"),
    );
    expect(mockShowToast).toHaveBeenCalledWith(
      "Added Deep Umbra (accumulated shadows) to this project.",
      "success",
    );
  });

  test("an add that installs libraries shows the restart notice", async () => {
    mockApi.installToProject.mockResolvedValue({
      packages: [...mockLockfile, "model.scout.deep-umbra@1"],
      restartRecommended: { libs: ["onnxruntime"], reason: "native extension" },
    });
    renderModelDrawer();
    const deepUmbra = await modelCard("model.scout.deep-umbra@1");
    fireEvent.click(within(deepUmbra).getByRole("button", { name: "Add to project" }));
    const review = await screen.findByRole("dialog", { name: "" });
    await act(async () => {
      fireEvent.click(within(review).getByRole("button", { name: "Add to project" }));
    });
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("onnxruntime");
  });

  test("Remove asks first, then takes the model out of the dataflow", async () => {
    renderModelDrawer();
    await modelCard("model.curio.ddrnet23-slim@1");
    fireEvent.click(tab("In project"));
    const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
    fireEvent.click(within(ddrnet).getByRole("button", { name: "Remove from project" }));
    const confirm = await screen.findByRole("dialog", { name: "Remove DDRNet23-Slim (street scenes)?" });
    expect(mockApi.uninstallFromProject).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
    });
    await waitFor(() =>
      expect(mockApi.uninstallFromProject).toHaveBeenCalledWith("p1", "model.curio.ddrnet23-slim@1"),
    );
  });

  test("the footer imports a package archive into the dataflow", async () => {
    renderModelDrawer();
    await modelCard("model.curio.ddrnet23-slim@1");
    const drawer = document.querySelector(MODEL_DRAWER) as HTMLElement;
    expect(within(drawer).getByRole("button", { name: "Import package" })).toBeInTheDocument();
    // Node-only: a model is not written from a Python function.
    expect(within(drawer).queryByRole("button", { name: /New node from a Python function/ })).toBeNull();
    const input = drawer.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["zip"], "segformer.curio.zip");
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });
    await waitFor(() => expect(mockApi.uploadArchive).toHaveBeenCalled());
    await waitFor(() =>
      expect(mockApi.installToProject).toHaveBeenCalledWith("p1", "imported.xabc123def456@1"),
    );
  });

  test("View details opens the details modal with the model's fields", async () => {
    renderModelDrawer();
    const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
    fireEvent.click(within(ddrnet).getByRole("button", { name: "View DDRNet23-Slim (street scenes) details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    expect(modal).toHaveTextContent("Weights license");
    expect(modal).toHaveTextContent("MIT; trained on Cityscapes");
    expect(modal).toHaveTextContent("Code license");
    expect(modal).toHaveTextContent("Image Segmentation");
  });

  test("a card dropped on a node that runs a model sets that node's model", async () => {
    renderModelDrawer();
    const segformer = await modelCard("imported.xabc123def456@1");
    // The card is the drag source, with the model's id on it for the canvas.
    expect(segformer).toHaveAttribute("data-model-id", "imported.xabc123def456");
    expect(segformer).toHaveAttribute("draggable", "true");
    const dataTransfer = fakeDataTransfer();
    fireEvent.dragStart(segformer, { dataTransfer });
    expect(dataTransfer.effectAllowed).toBe("copy");

    // What the node's drop handler does with that same DataTransfer.
    const node = {
      nodeId: "seg-1",
      code: 'folder = curio_load_model("model.curio.ddrnet23-slim")\nreturn segment(folder, input_1)',
    };
    const model = packages.readModelDragPayload(dataTransfer);
    expect(model?.modelId).toBe("imported.xabc123def456");
    expect(packages.canApplyModelToNode(node)).toBe(true);
    const applied = packages.applyModelToNodeData(node, model!);
    expect(applied.code).toBe(
      'folder = curio_load_model("imported.xabc123def456")\nreturn segment(folder, input_1)',
    );
    expect(applied.modelRefs).toEqual([
      { id: "imported.xabc123def456", name: "SegFormer B0 (ADE20K)" },
    ]);
  });

  test("while a card is dragged, the drawer lets the drag through to the canvas", async () => {
    renderModelDrawer();
    const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
    const root = document.querySelector(MODEL_DRAWER) as HTMLElement;
    expect(root).not.toHaveAttribute("data-dragging");
    // Text dragged out of the search box is not a card: the scrim stays.
    fireEvent.dragStart(screen.getByPlaceholderText("Search models, publishers, tags…"));
    expect(root).not.toHaveAttribute("data-dragging");

    fireEvent.dragStart(ddrnet, { dataTransfer: fakeDataTransfer() });
    expect(root).toHaveAttribute("data-dragging", "true");
    fireEvent.dragEnd(ddrnet);
    expect(root).not.toHaveAttribute("data-dragging");
  });

  test("a node that does not run a model is refused", async () => {
    renderModelDrawer();
    const ddrnet = await modelCard("model.curio.ddrnet23-slim@1");
    const dataTransfer = fakeDataTransfer();
    fireEvent.dragStart(ddrnet, { dataTransfer });
    const loader = { nodeId: "load-1", code: 'return curio_data_path("data.x")' };
    expect(packages.canApplyModelToNode(loader)).toBe(false);
    expect(packages.applyModelToNodeData(loader, packages.readModelDragPayload(dataTransfer)!)).toBe(loader);
  });
});

describe("the canvas Node Catalog drawer", () => {
  test("lists no model package, in either tab, and counts none in the project", async () => {
    render(
      <MemoryRouter>
        <NodeCatalogDrawer presented onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(card(NODE_DRAWER, "scout.raster-conversion@1")).not.toBeNull());
    expect(card(NODE_DRAWER, "curio.builtin@1")).not.toBeNull();
    for (const dirName of [
      "model.curio.ddrnet23-slim@1",
      "model.scout.deep-umbra@1",
      "imported.xabc123def456@1",
    ]) {
      expect(card(NODE_DRAWER, dirName)).toBeNull();
    }
    // The lockfile's node package and the builtin, never the model package.
    expect(tab("In project")).toHaveTextContent(/^In project2$/);
    fireEvent.click(tab("In project"));
    await waitFor(() => expect(card(NODE_DRAWER, "model.curio.ddrnet23-slim@1")).toBeNull());
    expect(card(NODE_DRAWER, "scout.raster-conversion@1")).not.toBeNull();
  });
});

describe("the node's drop handler", () => {
  const styles = read("components/styles.tsx");

  test("reads a model drag and applies it, or says why it cannot", () => {
    expect(styles).toContain("readModelDragPayload(e.dataTransfer)");
    expect(styles).toContain("canApplyModelToNode(live)");
    expect(styles).toContain("applyModelToNodeData(live, model)");
    expect(styles).toContain("showToast(`Model set to ${model.name}`, \"success\")");
    expect(styles).toContain('showToast("This node does not run a model", "warning")');
  });

  test("applies the editor's live text, not a stale copy", () => {
    expect(styles).toContain("code: code ?? data.code ?? data.defaultCode");
  });

  test("listens in the capture phase, ahead of Monaco, and accepts every model dragover", () => {
    // A refused dragover cancels the drop, and then the refusal toast could
    // never fire; a bubble-phase listener loses the event to Monaco.
    expect(styles).toContain('el.addEventListener("dragover", handleDragOver, true)');
    expect(styles).toContain('el.addEventListener("drop", handleDrop, true)');
    const over = styles.slice(styles.indexOf("const handleDragOver = (e: DragEvent) => {"));
    const modelBranch = over.slice(0, over.indexOf("if (!hasDatasetDrag(e.dataTransfer)) return;"));
    expect(modelBranch).toContain("hasModelDrag(e.dataTransfer)");
    expect(modelBranch).toContain("e.preventDefault()");
    expect(modelBranch).not.toContain("canApply");
  });

  test("takes the model drag from the packages service", () => {
    expect(styles).toMatch(/from "\.\.\/services\/packages(\/modelApplication)?"/);
    expect(styles).not.toContain("services/modelCatalog");
  });
});
