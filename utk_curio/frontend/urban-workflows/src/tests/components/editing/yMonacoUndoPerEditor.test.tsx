/**
 * Ctrl+Z in a node's code editor undoes that node's typing, of this tab's
 * own (`useYMonacoBinding`). The chord is an action of each editor: a Monaco
 * command is bound for every editor on the page, the last one bound winning,
 * so with two nodes on the canvas Ctrl+Z in the first ran the second's undo
 * and undid nothing.
 *
 * y-monaco is stubbed: what it would type into the doc is typed here with the
 * binding as the origin, as y-monaco does.
 */
import React from "react";
import { render, waitFor, act } from "@testing-library/react";

const mockBindings: Array<{ ytext: any; model: any }> = [];
jest.mock("y-monaco", () => ({
  MonacoBinding: class {
    ytext: any;
    model: any;
    constructor(ytext: any, model: any) {
      this.ytext = ytext;
      this.model = model;
      mockBindings.push(this);
    }
    destroy() {}
  },
}));

import { DataflowDocContext } from "../../../providers/collab/docContext";
import { DataflowDocProvider } from "../../../providers/collab/docProvider";
import { dataflowToDoc } from "../../../providers/collab/docMapping";
import { useYMonacoBinding } from "../../../components/editing/useYMonacoBinding";

const MONACO = { KeyMod: { CtrlCmd: 2048, Shift: 1024 }, KeyCode: { KeyZ: 56, KeyY: 55 } };
const CODE = "x = 1\n";

function fakeEditor() {
  const actions: Array<{ id: string; keybindings: number[]; run: () => void }> = [];
  const model = { getValue: () => CODE, onDidChangeContent: () => ({ dispose() {} }) };
  return {
    actions,
    getModel: () => model,
    addAction: (action: any) => {
      actions.push(action);
      return { dispose() {} };
    },
    onDidFocusEditorText: () => ({ dispose() {} }),
    onDidBlurEditorText: () => ({ dispose() {} }),
    hasTextFocus: () => false,
    trigger: jest.fn(),
  };
}

const Bound: React.FC<{ editor: any; nodeId: string }> = ({ editor, nodeId }) => {
  useYMonacoBinding(editor, MONACO, nodeId, { canWrite: true, baselineRef: { current: CODE } });
  return null;
};

test("Ctrl+Z in one node's editor undoes that node's typing, never another's", async () => {
  mockBindings.length = 0;
  const provider = new DataflowDocProvider("project-undo", { canWrite: true });
  dataflowToDoc({
    name: "",
    nodes: [
      { id: "a", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: CODE },
      { id: "b", type: "curio.builtin/computation-analysis", x: 600, y: 0, content: CODE },
    ],
    edges: [],
  }, provider.doc, "doc-1");
  provider.synced = true;
  const first = fakeEditor();
  const second = fakeEditor();
  render(
    <DataflowDocContext.Provider value={{ provider, synced: true }}>
      <Bound editor={first} nodeId="a" />
      <Bound editor={second} nodeId="b" />
    </DataflowDocContext.Provider>,
  );
  await waitFor(() => expect(mockBindings).toHaveLength(2));

  const text = (id: string) => ((provider.doc.getMap("nodes").get(id) as any).get("content") as any);
  const bindingOf = (id: string) => mockBindings.find((binding) => binding.ytext === text(id))!;
  // Typing in each node's editor, as y-monaco writes it.
  act(() => provider.doc.transact(() => text("a").insert(0, "# in a\n"), bindingOf("a")));
  act(() => provider.doc.transact(() => text("b").insert(0, "# in b\n"), bindingOf("b")));

  // Each editor binds the chord to its own undo.
  const undo = (editor: ReturnType<typeof fakeEditor>) => editor.actions.find((action) =>
    action.keybindings.includes(MONACO.KeyMod.CtrlCmd | MONACO.KeyCode.KeyZ))!;
  expect(undo(first)).toBeDefined();
  act(() => undo(first).run());

  expect(text("a").toString()).toBe(CODE);
  expect(text("b").toString()).toBe("# in b\n" + CODE);
  provider.destroy();
});
