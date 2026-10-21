/**
 * #1022: each of a node's runs in the provenance drawer reads "In: <kinds> |
 * Out: <kinds>" (utils/nodeRuns runKinds). Both sides read a dash on every
 * run, whatever the run read and returned: no run was filed with its kinds.
 *
 * This files a code node's run as its reply comes back, through the code a run
 * in the browser and a run on the server share (utils/executionResult), into
 * the real provider, and reads the run the drawer lists for it.
 */
import React from 'react';
import { act, fireEvent, render } from '@testing-library/react';

const mockNodeId = '3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57';
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ nodes: [{ id: mockNodeId }] }),
}));

import ProvenanceProvider, { useProvenanceContext } from '../../../providers/ProvenanceProvider';
import { NodeRunsProvenance } from '../../../components/provenance/NodeRunsProvenance';
import { recordExecProvenance } from '../../../utils/executionResult';

/** The node's input as the backend names it in its reply: one table. */
const INPUT = { path: 'art-in', dataType: 'dataframe' };

/** The run the drawer lists after one run whose reply was *reply*. */
function runAfterARun(reply: object): HTMLElement {
  const seen: { provenance?: ReturnType<typeof useProvenanceContext> } = {};
  const Probe = () => {
    seen.provenance = useProvenanceContext();
    return null;
  };
  const { container } = render(
    <ProvenanceProvider>
      <Probe />
      <NodeRunsProvenance nodeId={mockNodeId} restore={jest.fn()} onNodeGone={jest.fn()} />
    </ProvenanceProvider>,
  );
  act(() => {
    recordExecProvenance(seen.provenance!.nodeExecProv, {
      startedAt: new Date(),
      finishedAt: new Date(),
      workflowName: 'wf',
      nodeId: mockNodeId,
      input: INPUT,
      reply,
      code: 'return input_0.set_geometry("geom")',
    });
  });
  const run = container.querySelector<HTMLElement>('[data-provenance-item]');
  expect(run).not.toBeNull();
  return run as HTMLElement;
}

test("a run names the kinds of data it read and returned", () => {
  const run = runAfterARun({
    stdout: [], stderr: '', input: INPUT, output: { path: 'art-out', dataType: 'geodataframe' },
  });

  expect(run.textContent).toMatch(/In:\s+DATAFRAME\s+\|\s+Out:\s+GEODATAFRAME/);
});

test("a failed run says what it read, and that it returned an error", () => {
  const run = runAfterARun({
    stdout: [], stderr: "Traceback (most recent call last):\nKeyError: 'geom'", input: INPUT,
    output: { path: '', dataType: 'str' },
  });

  expect(run.textContent).toMatch(/In:\s+DATAFRAME\s+\|\s+Out:\s+ERROR/);
});

test("opened, a run shows its kinds again with the code that ran", () => {
  const run = runAfterARun({
    stdout: [], stderr: '', input: INPUT, output: { path: 'art-out', dataType: 'geodataframe' },
  });
  fireEvent.click(run.querySelector('button')!);

  expect(run.querySelector('pre')?.textContent).toBe('return input_0.set_geometry("geom")');
  expect(run.textContent?.match(/In:\s+DATAFRAME\s+\|\s+Out:\s+GEODATAFRAME/g)).toHaveLength(2);
});

// A Map Edits node's Apply, Remove or put back is an entry of its own.
describe("an edit in the drawer", () => {
  const EDIT_CODE = 'return curio_map_edits(\n    input_0,\n    key="building_id",\n    remove=[12],\n    change={},\n)\n';

  function editInTheDrawer(restore = jest.fn()) {
    const seen: { provenance?: ReturnType<typeof useProvenanceContext> } = {};
    const Probe = () => {
      seen.provenance = useProvenanceContext();
      return null;
    };
    const { container } = render(
      <ProvenanceProvider>
        <Probe />
        <NodeRunsProvenance nodeId={mockNodeId} restore={restore} onNodeGone={jest.fn()} />
      </ProvenanceProvider>,
    );
    act(() => { seen.provenance!.nodeEditProv(mockNodeId, EDIT_CODE, 'remove building_id 12'); });
    const edit = container.querySelector<HTMLElement>('[data-provenance-item]');
    expect(edit).not.toBeNull();
    return { edit: edit as HTMLElement, restore, seen };
  }

  test("reads what it changed, not the kinds of data a run reads", () => {
    const { edit } = editInTheDrawer();
    expect(edit.textContent).toContain('remove building_id 12');
    expect(edit.textContent).not.toMatch(/In:/);
  });

  test("opened, it shows when it was made and the code it left, and puts that code back", () => {
    const { edit, restore, seen } = editInTheDrawer();
    fireEvent.click(edit.querySelector('button')!);

    expect(edit.textContent).toMatch(/Made \S/);
    expect(edit.textContent).not.toMatch(/Started|ran for/);
    expect(edit.querySelector('pre')?.textContent).toBe(EDIT_CODE);
    expect(edit.textContent).toContain('The next run or edit branches from this one');
    const putBack = Array.from(edit.querySelectorAll('button')).find((b) => b.textContent === 'Put this code back in the node')!;
    fireEvent.click(putBack);
    expect(restore).toHaveBeenCalledWith(EDIT_CODE);
    const [record] = seen.provenance!.provenanceGraphNodes[mockNodeId];
    expect(seen.provenance!.selectedParentExecRef.current[mockNodeId]).toBe(record.id);
  });
});
