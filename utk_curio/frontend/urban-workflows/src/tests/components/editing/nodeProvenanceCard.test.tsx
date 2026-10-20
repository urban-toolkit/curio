/**
 * #1022: a node's Provenance tab draws each run as a card whose second line
 * reads "In: <kinds> | Out: <kinds>" (NodeProvenance.tsx). Both sides read a
 * dash on every card, whatever the run read and returned: no run was filed
 * with its kinds.
 *
 * This files a code node's run as its reply comes back, through the code a run
 * in the browser and a run on the server share (utils/executionResult), into
 * the real provider, and reads the card the tab draws for it.
 */
import React from 'react';
import { act, render } from '@testing-library/react';

// The tab's graph draws each run with the card it registers for runs. Placing
// the cards needs a browser's layout, so this stand-in draws each card as it is.
jest.mock('reactflow', () => ({
  __esModule: true,
  default: ({ nodes, nodeTypes }: any) => (
    <div data-testid="runs">
      {nodes.map((node: any) => {
        const Card = nodeTypes[node.type];
        return <Card key={node.id} id={node.id} data={node.data} />;
      })}
    </div>
  ),
  ReactFlowProvider: ({ children }: any) => <>{children}</>,
  Controls: () => null,
  Handle: () => null,
  BaseEdge: () => null,
  Position: { Left: 'left', Right: 'right' },
  useReactFlow: () => ({ fitView: () => undefined }),
  useStore: () => undefined,
  getSmoothStepPath: () => ['M0,0'],
}));

import ProvenanceProvider, { useProvenanceContext } from '../../../providers/ProvenanceProvider';
import NodeProvenance from '../../../components/editing/NodeProvenance';
import { recordExecProvenance } from '../../../utils/executionResult';

const NODE_ID = '3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57';
/** The node's input as the backend names it in its reply: one table. */
const INPUT = { path: 'art-in', dataType: 'dataframe' };

/** The node's open Provenance tab after one run whose reply was *reply*. */
function tabAfterARun(reply: object): HTMLElement {
  const seen: { provenance?: ReturnType<typeof useProvenanceContext> } = {};
  const Probe = () => {
    seen.provenance = useProvenanceContext();
    return null;
  };
  render(
    <ProvenanceProvider>
      <Probe />
      <NodeProvenance data={{ nodeId: NODE_ID }} setCode={jest.fn()} active />
    </ProvenanceProvider>,
  );
  act(() => {
    recordExecProvenance(seen.provenance!.nodeExecProv, {
      startedAt: new Date(),
      finishedAt: new Date(),
      workflowName: 'wf',
      nodeId: NODE_ID,
      input: INPUT,
      reply,
      code: 'return input_0.set_geometry("geom")',
    });
  });
  const runs = document.querySelector('[data-testid="runs"]');
  expect(runs).not.toBeNull();
  return runs as HTMLElement;
}

test("a run's card names the kinds of data it read and returned", () => {
  const tab = tabAfterARun({
    stdout: [], stderr: '', input: INPUT, output: { path: 'art-out', dataType: 'geodataframe' },
  });

  expect(tab.textContent).toMatch(/In:\s+DATAFRAME\s+\|\s+Out:\s+GEODATAFRAME/);
});

test("a failed run's card says what it read, and that it returned an error", () => {
  const tab = tabAfterARun({
    stdout: [], stderr: "Traceback (most recent call last):\nKeyError: 'geom'", input: INPUT,
    output: { path: '', dataType: 'str' },
  });

  expect(tab.textContent).toMatch(/In:\s+DATAFRAME\s+\|\s+Out:\s+ERROR/);
});
