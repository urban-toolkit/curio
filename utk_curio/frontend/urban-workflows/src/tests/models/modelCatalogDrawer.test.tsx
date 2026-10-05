/**
 * The canvas Model Catalog drawer, and a model dropped from it onto a node.
 *
 * The drop itself is handled in `NodeContainer` (components/styles.tsx), which
 * needs the whole provider stack to render (see nodeContainerBorder.test.tsx).
 * So the two halves are checked where each lives: the drag a card starts, then
 * the same payload read back off the same DataTransfer and applied to a node's
 * data exactly as the drop handler applies it; and, from the source, that the
 * handler is wired that way.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { ModelCatalogDrawer } from "../../components/models/catalog/ModelCatalogDrawer";
import {
  applyModelToNodeData,
  canApplyModelToNode,
  endModelDrag,
  invalidateModelCatalogCache,
  readModelDragPayload,
} from "../../services/modelCatalog";
import { downloadedModel, shippedModel } from "../_support/modelRows";

jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => "token"),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectDirty: false }),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require("../../utils/authApi") as { apiFetch: jest.Mock };

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

function renderDrawer() {
  return render(
    <MemoryRouter>
      <ModelCatalogDrawer presented onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
    </MemoryRouter>,
  );
}

function card(id: string): HTMLElement {
  const el = document.querySelector(`[data-curio-model-catalog-drawer] [data-model-id="${id}"]`);
  if (!el) throw new Error(`no card for ${id}`);
  return el as HTMLElement;
}

beforeEach(() => {
  invalidateModelCatalogCache();
  apiFetch.mockReset();
  apiFetch.mockResolvedValue({ items: [shippedModel(), downloadedModel()] });
});

afterEach(() => endModelDrag());

describe("the canvas Model Catalog drawer", () => {
  test("lists every model as a card", async () => {
    renderDrawer();
    expect(await screen.findByText("DDRNet23-Slim (street scenes)")).toBeInTheDocument();
    expect(screen.getByText("SegFormer B0 (ADE20K)")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Model Catalog" })).toBeInTheDocument();
  });

  test("only a downloaded model's card offers Delete", async () => {
    renderDrawer();
    await screen.findByText("SegFormer B0 (ADE20K)");
    expect(
      within(card("model.curio.ddrnet23-slim")).queryByRole("button", { name: "Delete" }),
    ).toBeNull();
    fireEvent.click(within(card("imported.xabc123def456")).getByRole("button", { name: "Delete" }));
    expect(
      await screen.findByRole("dialog", { name: 'Permanently delete "SegFormer B0 (ADE20K)"?' }),
    ).toBeInTheDocument();
  });

  test("a card dropped on a node that runs a model sets that node's model", async () => {
    renderDrawer();
    await screen.findByText("SegFormer B0 (ADE20K)");
    const dataTransfer = fakeDataTransfer();
    fireEvent.dragStart(card("imported.xabc123def456"), { dataTransfer });
    expect(dataTransfer.effectAllowed).toBe("copy");

    // What the node's drop handler does with that same DataTransfer.
    const node = {
      nodeId: "seg-1",
      code: 'folder = curio_load_model("model.curio.ddrnet23-slim")\nreturn segment(folder, input_1)',
    };
    const model = readModelDragPayload(dataTransfer);
    expect(model?.modelId).toBe("imported.xabc123def456");
    expect(canApplyModelToNode(node)).toBe(true);
    const applied = applyModelToNodeData(node, model!);
    expect(applied.code).toBe(
      'folder = curio_load_model("imported.xabc123def456")\nreturn segment(folder, input_1)',
    );
    expect(applied.modelRefs).toEqual([
      { id: "imported.xabc123def456", name: "SegFormer B0 (ADE20K)" },
    ]);
  });

  test("a node that does not run a model is refused", async () => {
    renderDrawer();
    await screen.findByText("DDRNet23-Slim (street scenes)");
    const dataTransfer = fakeDataTransfer();
    fireEvent.dragStart(card("model.curio.ddrnet23-slim"), { dataTransfer });
    const loader = { nodeId: "load-1", code: 'return curio_data_path("data.x")' };
    expect(canApplyModelToNode(loader)).toBe(false);
    expect(applyModelToNodeData(loader, readModelDragPayload(dataTransfer)!)).toBe(loader);
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
});
