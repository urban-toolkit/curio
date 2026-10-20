/**
 * A node's Provenance pill opens the node's runs in the provenance drawer: it
 * is not a tab, and the node keeps the pane it shows. Putting a run back from
 * the drawer shows the node's editor with that run's code, as loaded code
 * reaches it: nothing runs and no output is written.
 */
import React from "react";
import { act, fireEvent, render } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ dashboardOn: false }),
}));

jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: any) => <textarea data-testid="monaco" value={value ?? ""} readOnly />,
}));

jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    enabled: false,
    connected: false,
    users: [],
    proposals: [],
    currentUserId: null,
    requestCodeChange: jest.fn(),
    approveCodeChange: jest.fn(),
    rejectCodeChange: jest.fn(),
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

jest.mock("../../components/editing/WidgetsEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/editing/GrammarEditor", () => ({
  __esModule: true,
  default: ({ defaultValue, restoredCode }: any) => (
    <div
      data-testid="grammar-editor"
      data-default={defaultValue}
      data-restored={restoredCode?.code}
      data-restore-nonce={restoredCode?.nonce}
    />
  ),
}));

import NodeEditor from "../../components/editing/NodeEditor";
import { NodeHeaderSlotContext } from "../../components/editing/nodeHeaderSlot";
import {
  type NodeProvenanceTarget,
  ProvenanceDrawerContext,
} from "../../providers/provenanceDrawerContext";

const OUTPUT_ID = "vega-n1";

function props(): Record<string, any> {
  return {
    setSendCodeCallback: jest.fn(),
    setOutputCallback: jest.fn(),
    data: { nodeId: "n1", outputCallback: jest.fn() },
    output: { code: "", content: "" },
    nodeType: "curio.builtin/vis-vega",
    readOnly: false,
    applyGrammar: jest.fn(),
    code: false,
    grammar: true,
    widgets: false,
    defaultValue: '{"mark": "point"}',
    outputId: OUTPUT_ID,
  };
}

function mount(p: Record<string, any> = props(), drawer = true) {
  const slot = document.createElement("div");
  document.body.appendChild(slot);
  const openNodeProvenance = jest.fn<void, [NodeProvenanceTarget]>();
  const editor = <NodeEditor {...(p as React.ComponentProps<typeof NodeEditor>)} />;
  const utils = render(
    <NodeHeaderSlotContext.Provider value={slot}>
      {drawer ? (
        <ProvenanceDrawerContext.Provider
          value={{
            openDataflowProvenance: jest.fn(),
            openNodeProvenance,
            closeProvenance: jest.fn(),
            isProvenanceOpen: false,
          }}
        >
          {editor}
        </ProvenanceDrawerContext.Provider>
      ) : (
        editor
      )}
    </NodeHeaderSlotContext.Provider>,
  );
  const pill = (key: string) => slot.querySelector(`[data-rr-ui-event-key="${key}"]`) as HTMLElement | null;
  return { ...utils, p, slot, pill, openNodeProvenance };
}

describe("a node's Provenance pill", () => {
  test("opens the node's runs in the drawer, named as its header names it", async () => {
    const { pill, openNodeProvenance } = mount();
    await act(async () => {
      fireEvent.click(pill("provenance")!);
    });
    expect(openNodeProvenance).toHaveBeenCalledTimes(1);
    const target = openNodeProvenance.mock.calls[0][0];
    expect(target.nodeId).toBe("n1");
    expect(target.title).toEqual(expect.any(String));
    expect(target.title.length).toBeGreaterThan(0);
    expect(typeof target.restore).toBe("function");
  });

  test("is not a tab: the node keeps the pane it shows, and has no provenance pane", async () => {
    const { container, pill } = mount();
    await act(async () => {
      fireEvent.click(pill("output")!);
    });
    await act(async () => {
      fireEvent.click(pill("provenance")!);
    });
    expect(pill("output")).toHaveClass("active");
    expect(pill("provenance")).not.toHaveClass("active");
    expect(container.querySelector('[id$="-tabpane-provenance"]')).toBeNull();
    expect(container.querySelectorAll(".tab-pane")).toHaveLength(2);
  });

  test("putting a run back shows the editor with that run's code, and runs nothing", async () => {
    const { getByTestId, pill, p, openNodeProvenance } = mount();
    await act(async () => {
      fireEvent.click(pill("output")!);
    });
    await act(async () => {
      fireEvent.click(pill("provenance")!);
    });
    const { restore } = openNodeProvenance.mock.calls[0][0];

    await act(async () => {
      restore('{"mark": "bar"}');
    });

    expect(pill("grammar")).toHaveClass("active");
    expect(pill("output")).not.toHaveClass("active");
    expect(getByTestId("grammar-editor")).toHaveAttribute("data-restored", '{"mark": "bar"}');
    expect(p.setOutputCallback).not.toHaveBeenCalled();
  });

  test("each put-back reaches the editor, the loaded code included", async () => {
    // A new default equal to the loaded code is never applied, so the code
    // goes to the editor as a put-back of its own, every time.
    const { getByTestId, pill, openNodeProvenance } = mount();
    await act(async () => {
      fireEvent.click(pill("provenance")!);
    });
    const { restore } = openNodeProvenance.mock.calls[0][0];

    await act(async () => {
      restore('{"mark": "point"}');
    });
    expect(getByTestId("grammar-editor")).toHaveAttribute("data-restored", '{"mark": "point"}');
    expect(getByTestId("grammar-editor")).toHaveAttribute("data-restore-nonce", "1");

    await act(async () => {
      restore('{"mark": "point"}');
    });
    expect(getByTestId("grammar-editor")).toHaveAttribute("data-restore-nonce", "2");
    // The node's default is left alone: the editors take the code as content.
    expect(getByTestId("grammar-editor")).toHaveAttribute("data-default", '{"mark": "point"}');
  });

  test("a node whose template turns provenance off has no pill", () => {
    const { pill } = mount({ ...props(), provenance: false });
    expect(pill("provenance")).toBeNull();
    expect(pill("grammar")).not.toBeNull();
  });

  test("outside a dataflow's drawer, a click changes nothing", async () => {
    const { pill } = mount(props(), false);
    await act(async () => {
      fireEvent.click(pill("provenance")!);
    });
    expect(pill("grammar")).toHaveClass("active");
    expect(pill("provenance")).not.toHaveClass("active");
  });
});
