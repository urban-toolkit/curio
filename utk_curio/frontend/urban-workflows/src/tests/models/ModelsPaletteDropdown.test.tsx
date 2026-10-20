/**
 * The MODELS palette in the left rail: the Agents palette's pattern, listing
 * the models the open dataflow declares (the model packages in its lockfile,
 * the drawer's In project) as rows to drag onto a node, the way the Data
 * Catalog palette lists "Datasets in project". The rows are read through the
 * packages service, the lockfile through the flow context.
 *
 * Code main lacks is reached through `require`, so main fails test by test.
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { ModelsPaletteDropdown } from "../../components/menus/nodes/modelsPalette";
import {
  builtinPackage,
  ddrnetPackage,
  deepUmbraPackage,
  importedModelPackage,
} from "../_support/modelPackages";

const DDRNET = "model.curio.ddrnet23-slim@1";
const DEEP_UMBRA = "model.scout.deep-umbra@1";
const SEGFORMER = "imported.xabc123def456@1";
/** Node packages a lockfile names beside its models. */
const NODE_PACKAGES = ["curio.builtin@1", "scout.rasters@1"];

const mockOpenDrawer = jest.fn();
const mockShowToast = jest.fn();
const mockNodes: Array<{ id: string; data: any }> = [];
const mockApi = {
  catalog: jest.fn(),
  listInstalled: jest.fn(),
  getDefaults: jest.fn(),
  weightsLicense: jest.fn(),
};

jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: new Proxy({}, { get: (_target, name: string) => (mockApi as any)[name] }),
}));
jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn().mockResolvedValue({ items: [] }),
  getToken: jest.fn(() => "token"),
}));
jest.mock("../../providers/FlowProvider", () => {
  // A context, as the real provider's is: a lockfile write (an Add, a Remove)
  // renders again what reads it.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createContext, useContext } = require("react");
  const mockFlowContext = createContext({ projectDirty: false, packages: [] });
  return { mockFlowContext, useFlowContext: () => useContext(mockFlowContext) };
});
jest.mock("../../providers/modelCatalog", () => ({
  useModelCatalogDrawer: () => ({
    openModelCatalogDrawer: mockOpenDrawer,
    closeModelCatalogDrawer: jest.fn(),
    isModelCatalogDrawerOpen: false,
  }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("reactflow", () => ({
  useReactFlow: () => ({
    getNodes: () => mockNodes,
    setNodes: jest.fn(),
    fitView: jest.fn(),
  }),
}));
jest.mock("../../utils/fitViewWithMenuOffset", () => ({ fitViewWithMenuOffset: jest.fn() }));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const packages = require("../../services/packages");
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { mockFlowContext: FlowContext } = require("../../providers/FlowProvider");

/** The palette on a dataflow whose lockfile is *lockfile*. */
function Controlled({ lockfile }: { lockfile: string[] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <MemoryRouter>
      <FlowContext.Provider value={{ projectDirty: false, packages: lockfile }}>
        <ModelsPaletteDropdown open={open} setOpen={setOpen} />
      </FlowContext.Provider>
    </MemoryRouter>
  );
}

/** The rail's card: the one control titled for opening or closing the palette. */
function trigger(): HTMLElement {
  return screen.getByTitle(/model palette$/);
}

function panel(): HTMLElement {
  return screen.getByRole("region", { name: "Model palette" });
}

function openPanel(): HTMLElement {
  fireEvent.click(trigger());
  return panel();
}

/** The model ids the panel lists, in its order. */
function listed(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll("[data-model-id]")).map((el) => el.getAttribute("data-model-id") ?? "");
}

/** The panel's one accordion's summary row: its title and its count. */
function accordion(root: HTMLElement) {
  const summaries = root.querySelectorAll("summary");
  expect(summaries).toHaveLength(1);
  return within(summaries[0] as HTMLElement);
}

beforeEach(() => {
  jest.clearAllMocks();
  mockNodes.length = 0;
  // DDRNet is in the catalog and in the store; Deep Umbra only in the
  // catalog; SegFormer only in the store. A node package is no model.
  mockApi.catalog.mockResolvedValue({
    packages: [ddrnetPackage(), deepUmbraPackage(), builtinPackage()],
    families: [],
    catalogCollisions: [],
  });
  mockApi.listInstalled.mockResolvedValue({ packages: [ddrnetPackage(), builtinPackage(), importedModelPackage()] });
  mockApi.getDefaults.mockResolvedValue({ packages: [] });
});

afterEach(() => packages.endModelDrag?.());

describe("ModelsPaletteDropdown", () => {
  test("the trigger counts the dataflow's models before the palette is opened", async () => {
    render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, DEEP_UMBRA, SEGFORMER]} />);
    // Each model once: DDRNet's catalog row and store copy are one model.
    expect(await within(trigger()).findByText("3")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Model palette" })).toBeNull();
    // Read through the packages service, never /api/models.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    expect(require("../../utils/authApi").apiFetch).not.toHaveBeenCalled();
  });

  test("a dataflow that declares one model lists exactly that model, and counts 1", async () => {
    render(<Controlled lockfile={[...NODE_PACKAGES, DEEP_UMBRA]} />);
    expect(await within(trigger()).findByText("1")).toBeInTheDocument();
    const root = openPanel();
    expect(await within(root).findByText("Deep Umbra (accumulated shadows)")).toBeInTheDocument();
    // DDRNet is in the catalog and SegFormer in the account, and neither is
    // this dataflow's.
    expect(listed(root)).toEqual(["model.scout.deep-umbra"]);
    expect(within(root).queryByText("DDRNet23-Slim (street scenes)")).toBeNull();
    expect(within(root).queryByText("SegFormer B0 (ADE20K)")).toBeNull();
    const summary = accordion(root);
    expect(summary.getByText("Models in project")).toBeInTheDocument();
    expect(summary.getByText("1")).toBeInTheDocument();
    expect(within(root).queryByText("Add or import a model to use it here.")).toBeNull();
    expect(within(trigger()).getByText("1")).toBeInTheDocument();
  });

  test("a dataflow that declares no model shows the empty state, with Browse Model Catalog +", async () => {
    render(<Controlled lockfile={NODE_PACKAGES} />);
    const root = openPanel();
    // Once the listing is in, as the Data Catalog palette says it.
    expect(await within(root).findByText("Add or import a model to use it here.")).toBeInTheDocument();
    expect(listed(root)).toEqual([]);
    const summary = accordion(root);
    expect(summary.getByText("Models in project")).toBeInTheDocument();
    expect(summary.getByText("0")).toBeInTheDocument();
    expect(within(root).getByText("No models added yet.")).toBeInTheDocument();
    expect(within(trigger()).getByText("0")).toBeInTheDocument();
    fireEvent.click(within(root).getByRole("button", { name: "Browse Model Catalog +" }));
    expect(mockOpenDrawer).toHaveBeenCalledTimes(1);
  });

  test("the rows and the count follow the dataflow's lockfile, as an Add and a Remove write it", async () => {
    const { rerender } = render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET]} />);
    const root = openPanel();
    expect(await within(root).findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    expect(listed(root)).toEqual(["model.curio.ddrnet23-slim"]);
    // Deep Umbra added to the dataflow in the drawer.
    rerender(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, DEEP_UMBRA]} />);
    await waitFor(() =>
      expect(listed(panel()).sort()).toEqual(["model.curio.ddrnet23-slim", "model.scout.deep-umbra"]),
    );
    expect(within(trigger()).getByText("2")).toBeInTheDocument();
    // DDRNet removed from it.
    rerender(<Controlled lockfile={[...NODE_PACKAGES, DEEP_UMBRA]} />);
    await waitFor(() => expect(listed(panel())).toEqual(["model.scout.deep-umbra"]));
    expect(within(trigger()).getByText("1")).toBeInTheDocument();
  });

  test("a model that joins the lockfile before the listing holds it is listed once the listing is read again", async () => {
    // Import package and Save as package put a new model in the account and
    // in this dataflow's lockfile at once.
    const { rerender } = render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET]} />);
    const root = openPanel();
    expect(await within(root).findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    const another = importedModelPackage({
      packageId: "imported.xfeedbeef0001",
      dirName: "imported.xfeedbeef0001@1",
      name: "Another model",
    });
    mockApi.listInstalled.mockResolvedValue({
      packages: [ddrnetPackage(), builtinPackage(), importedModelPackage(), another],
    });
    rerender(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, "imported.xfeedbeef0001@1"]} />);
    expect(await within(panel()).findByText("Another model")).toBeInTheDocument();
    expect(listed(panel()).sort()).toEqual(["imported.xfeedbeef0001", "model.curio.ddrnet23-slim"]);
    expect(within(trigger()).getByText("2")).toBeInTheDocument();
  });

  test("opens into rows, a drag hint and the way into the drawer", async () => {
    render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, DEEP_UMBRA, SEGFORMER]} />);
    const root = within(openPanel());
    expect(await root.findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    expect(root.getByText("Deep Umbra (accumulated shadows)")).toBeInTheDocument();
    expect(root.getByText("SegFormer B0 (ADE20K)")).toBeInTheDocument();
    expect(root.queryByText("Curio built-in nodes")).toBeNull();
    expect(root.getByText("Drag a model onto a node to use it.")).toBeInTheDocument();
    fireEvent.click(root.getByRole("button", { name: "Browse Model Catalog +" }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  test("a row's drag handle starts a model drag", async () => {
    render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET]} />);
    openPanel();
    await screen.findByText("DDRNet23-Slim (street scenes)");
    const row = document.querySelector('[data-model-id="model.curio.ddrnet23-slim"]') as HTMLElement;
    const setData = jest.fn();
    fireEvent.dragStart(within(row).getByTitle("Drag onto a node that runs a model"), {
      dataTransfer: { setData, effectAllowed: "" },
    });
    expect(setData).toHaveBeenCalledWith(
      packages.MODEL_DRAG_MIME,
      JSON.stringify({
        modelId: "model.curio.ddrnet23-slim",
        name: "DDRNet23-Slim (street scenes)",
        runtime: "onnx",
        type: "semantic-segmentation",
      }),
    );
  });

  test("a row says when no node on the canvas uses its model", async () => {
    mockNodes.push({ id: "n1", data: { code: 'curio_load_model("imported.xabc123def456")' } });
    render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, SEGFORMER]} />);
    openPanel();
    fireEvent.click(await screen.findByText("DDRNet23-Slim (street scenes)"));
    expect(mockShowToast).toHaveBeenCalledWith("No nodes on the canvas use this model", "info");
    mockShowToast.mockReset();
    fireEvent.click(screen.getByText("SegFormer B0 (ADE20K)"));
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("a row's details are the model's details", async () => {
    render(<Controlled lockfile={[...NODE_PACKAGES, DEEP_UMBRA]} />);
    openPanel();
    await screen.findByText("Deep Umbra (accumulated shadows)");
    fireEvent.click(screen.getByRole("button", { name: "View Deep Umbra (accumulated shadows) details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    expect(modal).toHaveTextContent("Weights license");
    expect(modal).toHaveTextContent("deep_umbra");
  });

  test("a Discovery add reloads the rows", async () => {
    // The lockfile names a model the account does not hold yet, as a
    // dataflow shared before the model was added does.
    const another = importedModelPackage({
      packageId: "imported.xfeedbeef0001",
      dirName: "imported.xfeedbeef0001@1",
      name: "Another model",
    });
    render(<Controlled lockfile={[...NODE_PACKAGES, DDRNET, SEGFORMER, another.dirName]} />);
    await within(trigger()).findByText("2");
    mockApi.listInstalled.mockResolvedValue({
      packages: [ddrnetPackage(), builtinPackage(), importedModelPackage(), another],
    });
    packages.notifyPackageCatalogRefresh();
    await waitFor(() => expect(within(trigger()).getByText("3")).toBeInTheDocument());
  });
});
