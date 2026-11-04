import React from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';

jest.mock('../../api/historyApi', () => ({
    historyApi: {
        noteRun: jest.fn().mockResolvedValue({}),
        noteEdit: jest.fn().mockResolvedValue({}),
    },
}));

import ProvenanceProvider, { useProvenanceContext, NodeExecRecord } from '../../providers/ProvenanceProvider';
import { historyApi } from '../../api/historyApi';
import { setServerHistory, type ServerHistory } from '../../providers/history/serverHistory';

const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(ProvenanceProvider, null, children);

describe('ProvenanceProvider', () => {
    it('nodeExecProv stores a record in local state', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv(
                '2025-01-01T00:00:00Z', '2025-01-01T00:00:01Z',
                'workflow', 'node-1',
                ['DATAFRAME'], ['GEODATAFRAME'], 'df = df.head()'
            );
        });
        const nodes = result.current.provenanceGraphNodes;
        expect(nodes['node-1']).toHaveLength(1);
        expect(nodes['node-1'][0].code).toBe('df = df.head()');
        expect(nodes['node-1'][0].parentId).toBeNull();
        expect(nodes['node-1'][0].inputs).toEqual(['DATAFRAME']);
        expect(nodes['node-1'][0].outputs).toEqual(['GEODATAFRAME']);
    });

    it('nodeExecProv files a run under the node id it is given, dashes and all (#448)', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', '3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57', [], [], 'x=1');
        });
        expect(Object.keys(result.current.provenanceGraphNodes)).toEqual(['3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57']);
    });

    it('branching: second run after setSelectedExec uses first run id as parentId', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv('t1', 't2', 'wf', 'node-1', [], [], 'code1');
        });
        const firstId = result.current.provenanceGraphNodes['node-1'][0].id;
        act(() => { result.current.setSelectedExec('node-1', firstId); });
        act(() => {
            result.current.nodeExecProv('t3', 't4', 'wf', 'node-1', [], [], 'code2');
        });
        const records = result.current.provenanceGraphNodes['node-1'];
        expect(records).toHaveLength(2);
        expect(records[1].parentId).toBe(firstId);
    });

    it('consecutive runs without explicit setSelectedExec auto-chain (each run sets itself as parent)', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', 'node-2', [], [], 'run1');
        });
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', 'node-2', [], [], 'run2');
        });
        const records = result.current.provenanceGraphNodes['node-2'];
        expect(records).toHaveLength(2);
        expect(records[1].parentId).toBe(records[0].id);
    });

    it('loadNodeProvenance hydrates state and resets counter above max id', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        const mockData: Record<string, NodeExecRecord[]> = {
            'node-5': [{ id: 10, parentId: null, code: 'x=1', inputs: [], outputs: [], startTime: '', endTime: '' }],
        };
        act(() => { result.current.loadNodeProvenance(mockData); });
        expect(result.current.provenanceGraphNodes['node-5']).toHaveLength(1);
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', 'node-5', [], [], 'y=2');
        });
        const records = result.current.provenanceGraphNodes['node-5'];
        expect(records[1].id).toBeGreaterThan(10);
    });

    it('getAllNodeProvenance returns current state', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', 'node-x', [], [], 'z=3');
        });
        const all = result.current.getAllNodeProvenance();
        expect(all['node-x']).toBeDefined();
        expect(all['node-x']).toHaveLength(1);
    });

    it('ids are unique across multiple nodes', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.nodeExecProv('t', 't', 'wf', 'node-a', [], [], 'a');
            result.current.nodeExecProv('t', 't', 'wf', 'node-b', [], [], 'b');
        });
        const idA = result.current.provenanceGraphNodes['node-a'][0].id;
        const idB = result.current.provenanceGraphNodes['node-b'][0].id;
        expect(idA).not.toBe(idB);
    });
});

// A Map Editor node files each change made in its body as an entry of its own.
describe('an edit in node provenance', () => {
    it('is filed at once with the code it left and its label, reading and returning nothing', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => { result.current.nodeEditProv('edit-1', 'code 1', 'remove building_id 12'); });
        const [edit] = result.current.provenanceGraphNodes['edit-1'];
        expect(edit).toMatchObject({
            parentId: null, code: 'code 1', inputs: [], outputs: [], kind: 'edit', label: 'remove building_id 12',
        });
        expect(edit.startTime).not.toBe('');
        expect(edit.endTime).toBe(edit.startTime);
        expect(result.current.selectedParentExecRef.current['edit-1']).toBe(edit.id);
    });

    it('descends from the entry before it, a run or an edit, and a put-back entry is where the next one branches', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => { result.current.nodeEditProv('edit-1', 'code 1', 'remove building_id 12'); });
        act(() => { result.current.nodeExecProv('t', 't', 'wf', 'edit-1', ['GEODATAFRAME'], ['GEODATAFRAME'], 'code 1'); });
        act(() => { result.current.nodeEditProv('edit-1', 'code 2', 'height 60 on building_id 34'); });
        let records = result.current.provenanceGraphNodes['edit-1'];
        expect(records.map((r) => r.parentId)).toEqual([null, records[0].id, records[1].id]);
        expect(records.map((r) => r.kind)).toEqual(['edit', undefined, 'edit']);

        act(() => { result.current.setSelectedExec('edit-1', records[0].id); });
        act(() => { result.current.nodeEditProv('edit-1', 'code 3', 'put back building_id 12'); });
        records = result.current.provenanceGraphNodes['edit-1'];
        expect(records[3].parentId).toBe(records[0].id);
    });

    it('keeps the code an edit replaced only where no entry before it holds it, for Undo', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        // The node's first change: no entry holds the code it started from.
        act(() => { result.current.nodeEditProv('edit-1', 'code 1', 'Remove building_id 12', 'start'); });
        // The next one starts from the entry before it.
        act(() => { result.current.nodeEditProv('edit-1', 'code 2', 'Remove building_id 13', 'code 1'); });
        // One made after the code changed with no entry (a hand edit).
        act(() => { result.current.nodeEditProv('edit-1', 'code 4', 'Remove building_id 14', 'code 3'); });
        const records = result.current.provenanceGraphNodes['edit-1'];
        expect(records.map((r) => r.before)).toEqual(['start', undefined, 'code 3']);
    });

    it('moving the entry in use renders its views again, though nothing is filed', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => { result.current.nodeEditProv('edit-1', 'code 1', 'Remove building_id 12', 'start'); });
        const before = result.current.selectedRevision;
        act(() => { result.current.setSelectedExec('edit-1', null); });
        expect(result.current.selectedRevision).not.toBe(before);
        expect(result.current.selectedParentExecRef.current['edit-1']).toBeNull();
    });

    it('is nothing outside a provider: the context by default files no entry', () => {
        const { result } = renderHook(() => useProvenanceContext());
        expect(() => result.current.nodeEditProv('edit-1', 'code', 'label')).not.toThrow();
        expect(result.current.provenanceGraphNodes).toEqual({});
    });
});

describe('a dataflow loaded with its node histories', () => {
    const entry = (id: number, parentId: number | null, code: string, kind?: 'edit'): NodeExecRecord => ({
        id, parentId, code, inputs: [], outputs: [], startTime: '', endTime: '', ...(kind ? { kind, label: `edit ${id}` } : {}),
    });

    it("continues each node's history from its newest entry that holds the code it loaded with", () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.loadNodeProvenance(
                {
                    edits: [entry(1, null, 'a', 'edit'), entry(2, 1, 'b', 'edit'), entry(3, 2, 'a'), entry(4, 3, 'c', 'edit')],
                    code: [entry(5, null, 'x = 1'), entry(6, 5, 'x = 2')],
                },
                { edits: 'a', code: 'x = 1' },
            );
        });
        expect(result.current.selectedParentExecRef.current).toEqual({ edits: 3, code: 5 });

        act(() => { result.current.nodeEditProv('edits', 'd', 'edit 7'); });
        act(() => { result.current.nodeExecProv('t', 't', 'wf', 'code', [], [], 'x = 3'); });
        expect(result.current.provenanceGraphNodes.edits[4]).toMatchObject({ id: 7, parentId: 3 });
        expect(result.current.provenanceGraphNodes.code[2]).toMatchObject({ id: 8, parentId: 5 });
    });

    it('continues from the newest entry when none holds the code, and not from a new root', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => {
            result.current.loadNodeProvenance(
                { n1: [entry(2, null, 'a'), entry(9, 2, 'b'), entry(4, 2, 'c')], n2: [entry(1, null, 'q')] },
                { n1: 'hand-edited' },
            );
        });
        expect(result.current.selectedParentExecRef.current).toEqual({ n1: 9, n2: 1 });
        act(() => { result.current.nodeExecProv('t', 't', 'wf', 'n1', [], [], 'z'); });
        expect(result.current.provenanceGraphNodes.n1[3].parentId).toBe(9);
    });
});

// A canvas bound to the dataflow's doc: the server keeps the history, and the
// tab sends it each run and each edit made in a node's body.
describe('on a canvas whose history the server keeps', () => {
    const noteRun = historyApi.noteRun as jest.Mock;
    const noteEdit = historyApi.noteEdit as jest.Mock;
    const START = '2026-10-28T14:05:03.000Z';
    const END = '2026-10-28T14:05:04.000Z';

    function server(reads = true): ServerHistory & { whenKept: jest.Mock } {
        return { projectId: 'proj', reads: () => reads, whenKept: jest.fn().mockResolvedValue(true), codeOf: () => undefined };
    }

    afterEach(() => {
        act(() => setServerHistory(null));
        noteRun.mockClear();
        noteEdit.mockClear();
    });

    it("sends a run after the tab's changes are kept, and files nothing here", async () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        const bound = server();
        act(() => setServerHistory(bound));
        act(() => {
            result.current.nodeExecProv(START, END, 'wf', 'node-1', ['DATAFRAME'], ['VALUE'], 'return 1');
        });
        await waitFor(() => expect(noteRun).toHaveBeenCalledTimes(1));
        expect(noteRun).toHaveBeenCalledWith('proj', 'node-1', {
            code: 'return 1', inputs: ['DATAFRAME'], outputs: ['VALUE'], startTime: START, endTime: END,
        });
        expect(bound.whenKept).toHaveBeenCalled();
        expect(bound.whenKept.mock.invocationCallOrder[0]).toBeLessThan(noteRun.mock.invocationCallOrder[0]);
        expect(result.current.provenanceGraphNodes).toEqual({});
    });

    it("sends an edit made in a node's body under its label, and an agent's change not at all", async () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => setServerHistory(server()));
        act(() => {
            result.current.nodeEditProv('edit-1', 'code 1', 'Remove building_id 12', 'start');
            result.current.agentEditProv('py-1', 'x = 2', 'Node Builder', 'x = 1');
        });
        await waitFor(() => expect(noteEdit).toHaveBeenCalledTimes(1));
        expect(noteEdit).toHaveBeenCalledWith('proj', 'edit-1', 'Remove building_id 12');
        expect(noteRun).not.toHaveBeenCalled();
        expect(result.current.provenanceGraphNodes).toEqual({});
    });

    it("a watcher's tab sends nothing and files nothing", async () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        const bound = server(false);
        act(() => setServerHistory(bound));
        act(() => {
            result.current.nodeExecProv(START, END, 'wf', 'node-1', [], [], 'return 1');
            result.current.nodeEditProv('edit-1', 'code 1', 'Remove building_id 12');
        });
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 10));
        });
        expect(bound.whenKept).not.toHaveBeenCalled();
        expect(noteRun).not.toHaveBeenCalled();
        expect(noteEdit).not.toHaveBeenCalled();
        expect(result.current.provenanceGraphNodes).toEqual({});
    });

    it('binding sends the runs no save carried, and what was filed here goes', async () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => { result.current.nodeExecProv(START, END, 'wf', 'carried', [], [], 'saved run'); });
        // A save carries the history as it stands now.
        expect(result.current.getAllNodeProvenance().carried).toHaveLength(1);
        act(() => {
            result.current.nodeExecProv(START, END, 'wf', 'after', ['DATAFRAME'], ['VALUE'], 'later run');
            result.current.nodeEditProv('after', 'later edit', 'Remove building_id 3');
        });
        act(() => setServerHistory(server()));
        await waitFor(() => expect(noteRun).toHaveBeenCalledTimes(1));
        expect(noteRun).toHaveBeenCalledWith('proj', 'after', expect.objectContaining({ code: 'later run' }));
        expect(noteEdit).not.toHaveBeenCalled();
        expect(result.current.provenanceGraphNodes).toEqual({});
        expect(result.current.selectedParentExecRef.current).toEqual({});
    });

    it('the entry this tab chose stays the one in use while the node holds the code it left', () => {
        const { result } = renderHook(() => useProvenanceContext(), { wrapper });
        act(() => { result.current.chooseEntry('n1', 3, 'code 3'); });
        expect(result.current.chosenEntry('n1', 'code 3')).toBe(3);
        expect(result.current.chosenEntry('n1', 'someone else\'s code')).toBeUndefined();
        act(() => { result.current.chooseEntry('n1', null, 'before the first'); });
        expect(result.current.chosenEntry('n1', 'before the first')).toBeNull();
        expect(result.current.chosenEntry('n2', 'code 3')).toBeUndefined();
    });
});
