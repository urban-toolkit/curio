/**
 * #1248: a node has one name, its title. An agent at work's chip, in the
 * dock's row of people and among the canvas agents (`useAgentAtWorkText`),
 * names the node it is writing by that title, as the node's header does,
 * never by its template's label.
 */
import React from "react";
import { renderHook } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi } from "reactflow";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

import { useAgentAtWorkText } from "../../components/agents/attach/PeopleHere";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";

const PYTHON = "curio.builtin/python-computation@1";

/** A Python node renamed "Shade per park", as the canvas holds it. */
const NODES = [
  { id: "n1", position: { x: 0, y: 0 }, data: { nodeId: "n1", nodeType: PYTHON, title: "Shade per park" } },
];

beforeAll(() => {
  registerNode({
    id: PYTHON,
    category: "computation",
    label: "Python Computation",
    icon: faCircle,
    inputPorts: [],
    outputPorts: [],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
  } as unknown as NodeDescriptor);
});

/** Puts the node in React Flow's store, as a rendered canvas would. */
function Seed() {
  const store = useStoreApi();
  React.useLayoutEffect(() => {
    store.getState().setNodes(NODES as any);
  }, [store]);
  return null;
}

function Canvas({ children }: { children: React.ReactNode }) {
  return (
    <ReactFlowProvider>
      <Seed />
      {children}
    </ReactFlowProvider>
  );
}

test("an agent at work's chip names the node it is writing by its title", () => {
  const person: any = {
    key: "agent:a1",
    name: "Dataflow Builder",
    role: "editor",
    editing: ["n1"],
    agent: { askedBy: "Ana", skills: [], category: "builder", attachmentId: "a1" },
  };
  const { result } = renderHook(() => useAgentAtWorkText(person), { wrapper: Canvas });
  expect(result.current).toContain("editing Shade per park");
  expect(result.current).not.toContain("Python Computation");
});
