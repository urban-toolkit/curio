import { TrillGenerator } from '../../../TrillGenerator';

beforeEach(() => TrillGenerator.reset());
const map = JSON.stringify({ map: { layerRefs: [{ dataRef: 'upstream', isPick: true }] } });
function exported(code: string, defaultCode: string) {
  return TrillGenerator.generateTrill([{
    type: 'curio.builtin/autk-grammar', position: { x: 0, y: 0 },
    data: { nodeId: 'before', nodeType: 'curio.builtin/autk-grammar', code, defaultCode },
  }], [], 'Saved grammar diagnostic').dataflow.nodes[0].content;
}

test('characterizes the saved-grammar discrepancy: a diverged live buffer serializes data.code', () => {
  // This demonstrates the serializer behavior, not a browser reproduction of its trigger.
  expect(exported('{}', map)).toBe('{}');
});

test('a synchronized code/defaultCode pair preserves the complete map grammar', () => {
  expect(exported(map, map)).toBe(map);
});
