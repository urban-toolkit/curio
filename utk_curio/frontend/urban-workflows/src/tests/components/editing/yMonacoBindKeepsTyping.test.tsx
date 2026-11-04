/**
 * What a node's code editor holds when it binds to the dataflow's doc
 * (`useYMonacoBinding`). A canvas never saved binds once its create has made
 * the dataflow, whose doc holds the code as the create sent it; whatever was
 * typed while the create was out is only in the editor. An editor holding
 * something else than what was last written into it holds typing, which goes
 * into the doc as it binds. An editor holding just what was written into it
 * takes the doc's code, someone else's typing included.
 *
 * y-monaco is stubbed: the binding takes the doc's text into the editor, as
 * y-monaco does.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockBindings: Array<{ ytext: any; model: any }> = [];
jest.mock("y-monaco", () => ({
  MonacoBinding: class {
    ytext: any;
    model: any;
    constructor(ytext: any, model: any) {
      this.ytext = ytext;
      this.model = model;
      model.setValue(ytext.toString());
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
/** The code the node was given (its starter), what the create sent, and what
 *  the editor holds after typing on while the create was out. */
const STARTER = "x = 1\n";
const SENT = "x = 1\n# typed before the save\n";
const TYPED = "x = 1\n# typed before the save\n# typed while the create was out\n";

function fakeEditor(value: string) {
  let shown = value;
  const model = {
    getValue: () => shown,
    setValue: (next: string) => {
      shown = next;
    },
    onDidChangeContent: () => ({ dispose() {} }),
  };
  return {
    model,
    getModel: () => model,
    addAction: () => ({ dispose() {} }),
    onDidFocusEditorText: () => ({ dispose() {} }),
    onDidBlurEditorText: () => ({ dispose() {} }),
    hasTextFocus: () => false,
    trigger: jest.fn(),
  };
}

const Bound: React.FC<{ editor: any; baseline: string }> = ({ editor, baseline }) => {
  useYMonacoBinding(editor, MONACO, "a", { canWrite: true, baselineRef: { current: baseline } });
  return null;
};

/** The dataflow the create made, its doc holding the code as it was sent. */
function madeDataflow(): DataflowDocProvider {
  const provider = new DataflowDocProvider("project-made", { canWrite: true });
  dataflowToDoc({
    name: "",
    nodes: [{ id: "a", type: "curio.builtin/computation-analysis", x: 0, y: 0, content: SENT }],
    edges: [],
  }, provider.doc, "doc-1");
  provider.synced = true;
  return provider;
}

const codeIn = (provider: DataflowDocProvider) =>
  ((provider.doc.getMap("nodes").get("a") as any).get("content") as any).toString();

beforeEach(() => {
  mockBindings.length = 0;
});

test("what was typed while the create was out goes into the doc as the editor binds", async () => {
  const provider = madeDataflow();
  const editor = fakeEditor(TYPED);
  render(
    <DataflowDocContext.Provider value={{ provider, synced: true }}>
      <Bound editor={editor} baseline={STARTER} />
    </DataflowDocContext.Provider>,
  );
  await waitFor(() => expect(mockBindings).toHaveLength(1));

  expect(codeIn(provider)).toBe(TYPED);
  expect(editor.model.getValue()).toBe(TYPED);
  provider.destroy();
});

test("an editor holding only what was written into it takes the doc's code", async () => {
  const provider = madeDataflow();
  const editor = fakeEditor(STARTER);
  render(
    <DataflowDocContext.Provider value={{ provider, synced: true }}>
      <Bound editor={editor} baseline={STARTER} />
    </DataflowDocContext.Provider>,
  );
  await waitFor(() => expect(mockBindings).toHaveLength(1));

  expect(codeIn(provider)).toBe(SENT);
  expect(editor.model.getValue()).toBe(SENT);
  provider.destroy();
});
