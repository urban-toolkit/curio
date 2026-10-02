/**
 * The MODELS palette in the left rail: the Agents palette's pattern, listing
 * every model this account can run as rows to drag onto a node.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ModelsPaletteDropdown } from "../../components/menus/nodes/modelsPalette";
import { MODEL_DRAG_MIME, endModelDrag, invalidateModelCatalogCache } from "../../services/modelCatalog";
import { downloadedModel, shippedModel } from "../_support/modelRows";

const mockOpenDrawer = jest.fn();
const mockShowToast = jest.fn();
const mockNodes: Array<{ id: string; data: any }> = [];

jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(),
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
const { apiFetch } = require("../../utils/authApi") as { apiFetch: jest.Mock };

function Controlled() {
  const [open, setOpen] = React.useState(false);
  return <ModelsPaletteDropdown open={open} setOpen={setOpen} />;
}

beforeEach(() => {
  invalidateModelCatalogCache();
  apiFetch.mockReset();
  apiFetch.mockResolvedValue({ items: [shippedModel(), downloadedModel()] });
  mockOpenDrawer.mockReset();
  mockShowToast.mockReset();
  mockNodes.length = 0;
});

afterEach(() => endModelDrag());

describe("ModelsPaletteDropdown", () => {
  test("the trigger counts the models before the palette is opened", async () => {
    render(<Controlled />);
    const trigger = screen.getByRole("button", { name: /Model Catalog/ });
    expect(await within(trigger).findByText("2")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Model palette" })).toBeNull();
  });

  test("opens into rows, a drag hint and the way into the drawer", async () => {
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
    const panel = within(screen.getByRole("region", { name: "Model palette" }));
    expect(await panel.findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    expect(panel.getByText("SegFormer B0 (ADE20K)")).toBeInTheDocument();
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
      MODEL_DRAG_MIME,
      JSON.stringify({
        modelId: "model.curio.ddrnet23-slim",
        name: "DDRNet23-Slim (street scenes)",
        runtime: "onnx",
      }),
    );
  });

  test("a row says when no node on the canvas uses its model", async () => {
    mockNodes.push({ id: "n1", data: { code: 'curio_model("imported.xabc123def456")' } });
    render(<Controlled />);
    fireEvent.click(screen.getByRole("button", { name: /Model Catalog/ }));
    fireEvent.click(await screen.findByText("DDRNet23-Slim (street scenes)"));
    expect(mockShowToast).toHaveBeenCalledWith("No nodes on the canvas use this model", "info");
    mockShowToast.mockReset();
    fireEvent.click(screen.getByText("SegFormer B0 (ADE20K)"));
    expect(mockShowToast).not.toHaveBeenCalled();
  });
});
