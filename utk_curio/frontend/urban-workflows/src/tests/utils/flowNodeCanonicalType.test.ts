import { CURIO_UNIVERSAL_NODE_TYPE, NodeType } from '../../constants';
import {
  getFlowNodeCanonicalType,
  getUnversionedFlowNodeType,
  unversionedNodeType,
} from '../../utils/flowNodeCanonicalType';

describe('unversionedNodeType', () => {
  test('strips a trailing @<major>', () => {
    expect(unversionedNodeType('curio.builtin/vis-vega@1')).toBe('curio.builtin/vis-vega');
    expect(unversionedNodeType('ai.urbanlab.uhvi/uhvi-load@12')).toBe('ai.urbanlab.uhvi/uhvi-load');
  });

  test('returns non-canonical strings unchanged', () => {
    expect(unversionedNodeType('curio.builtin/vis-vega')).toBe('curio.builtin/vis-vega');
    expect(unversionedNodeType('PYTHON_COMPUTATION')).toBe('PYTHON_COMPUTATION');
    expect(unversionedNodeType('')).toBe('');
  });
});

describe('getFlowNodeCanonicalType / getUnversionedFlowNodeType', () => {
  test('universal nodes resolve the dispatcher id from data.nodeType', () => {
    const node = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: 'curio.builtin/vis-vega@1' },
    };
    expect(getFlowNodeCanonicalType(node)).toBe('curio.builtin/vis-vega@1');
    expect(getUnversionedFlowNodeType(node)).toBe('curio.builtin/vis-vega');
  });

  test('plain nodes keep their react-flow type', () => {
    const node = { type: 'curio.builtin/data-transformation@1' };
    expect(getFlowNodeCanonicalType(node)).toBe('curio.builtin/data-transformation@1');
    expect(getUnversionedFlowNodeType(node)).toBe('curio.builtin/data-transformation');
  });
});

/**
 * Edge cases carried over from the agent-catalog branch, which grew its own
 * copy of these helpers under different names before the two were unified.
 * They pin the *shape* the strip applies to, which the cases above do not.
 */
describe('unversionedNodeType only strips the canonical <pkg>/<template>@<major> shape', () => {
  test('an @ inside the template id is not a version', () => {
    expect(unversionedNodeType('a.pkg/tmpl@b@2')).toBe('a.pkg/tmpl@b@2');
  });

  test('an id with no package segment is left alone', () => {
    expect(unversionedNodeType('no-slash@2')).toBe('no-slash@2');
  });

  test('a trailing @ without digits is not a version', () => {
    expect(unversionedNodeType('weird@')).toBe('weird@');
    expect(unversionedNodeType('weird@abc')).toBe('weird@abc');
  });

  test('an @ before the slash is not a version', () => {
    expect(unversionedNodeType('mid@1dle/x')).toBe('mid@1dle/x');
  });
});

describe('getUnversionedFlowNodeType against the NodeType enum', () => {
  test('the versioned merge-flow regression: raw keeps the version, helper strips it', () => {
    const node = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: 'curio.builtin/merge-flow@1' },
    };
    expect(getFlowNodeCanonicalType(node) === NodeType.MERGE_FLOW).toBe(false);
    expect(getUnversionedFlowNodeType(node)).toBe(NodeType.MERGE_FLOW);
  });

  test('legacy unversioned specs keep matching', () => {
    const node = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: 'curio.builtin/merge-flow' },
    };
    expect(getUnversionedFlowNodeType(node)).toBe(NodeType.MERGE_FLOW);
  });

  test('non-universal nodes fall back to node.type, unversioned', () => {
    expect(getUnversionedFlowNodeType({ type: 'curio.builtin/data-pool@1' })).toBe(NodeType.DATA_POOL);
    expect(getUnversionedFlowNodeType({ type: undefined })).toBe('');
  });
});
