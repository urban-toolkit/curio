/**
 * The MODELS palette in the left rail: the Agents palette's pattern, listing
 * every model package this account can use (the catalog's and its own) as
 * rows to drag onto a node, read through the packages service.
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
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectDirty: false }),
}));
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

function Controlled() {
  const [open, setOpen] = React.useState(false);
  return (
    <MemoryRouter>
      <ModelsPaletteDropdown open={open} setOpen={setOpen} />
    </MemoryRouter>
  );
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
  test("the trigger counts the model packages before the palette is opened", async () => {
    render(<Controlled />);
    const trigger = screen.getByRole("button", { name: /Model Catalog/ });
    // Each model once: DDRNet's catalog row and store copy are one model.
    expect(await within(trigger).findByText("3")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Model palette" })).toBeNull();
    // Read through the packages service, never /api/models.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    expect(require("../../utils/authApi").apiFetch).not.toHaveBeenCalled();
  });

  test("opens into rows, a drag hint and the way into the drawer", async () => {
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
    const panel = within(screen.getByRole("region", { name: "Model palette" }));
    expect(await panel.findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    expect(panel.getByText("Deep Umbra (accumulated shadows)")).toBeInTheDocument();
    expect(panel.getByText("SegFormer B0 (ADE20K)")).toBeInTheDocument();
    expect(panel.queryByText("Curio built-in nodes")).toBeNull();
    expect(panel.getByText("Drag a model onto a node to use it.")).toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "Browse Model Catalog +" }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  test("a row's drag handle starts a model drag", async () => {
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
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
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
    fireEvent.click(await screen.findByText("DDRNet23-Slim (street scenes)"));
    expect(mockShowToast).toHaveBeenCalledWith("No nodes on the canvas use this model", "info");
    mockShowToast.mockReset();
    fireEvent.click(screen.getByText("SegFormer B0 (ADE20K)"));
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("a row's details are the model's details", async () => {
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
    await screen.findByText("Deep Umbra (accumulated shadows)");
    fireEvent.click(screen.getByRole("button", { name: "View Deep Umbra (accumulated shadows) details" }));
    const modal = await screen.findByRole("dialog", { name: "Model details" });
    expect(modal).toHaveTextContent("Weights license");
    expect(modal).toHaveTextContent("deep_umbra");
  });

  test("a Discovery add reloads the rows", async () => {
    render(<Controlled />);
    const trigger = screen.getByRole("button", { name: /Model Catalog/ });
    await within(trigger).findByText("3");
    const another = importedModelPackage({
      packageId: "imported.xfeedbeef0001",
      dirName: "imported.xfeedbeef0001@1",
      name: "Another model",
    });
    mockApi.listInstalled.mockResolvedValue({
      packages: [ddrnetPackage(), builtinPackage(), importedModelPackage(), another],
    });
    packages.notifyPackageCatalogRefresh();
    await waitFor(() => expect(within(trigger).getByText("4")).toBeInTheDocument());
  });
});
