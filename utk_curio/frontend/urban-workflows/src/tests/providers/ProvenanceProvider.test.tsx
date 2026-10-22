import React from 'react';
import { renderHook, act } from '@testing-library/react';
import ProvenanceProvider, { useProvenanceContext, NodeExecRecord } from '../../providers/ProvenanceProvider';

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

// A Map Edits node files each change made in its body as an entry of its own.
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
