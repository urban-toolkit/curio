import {
  getFlowNodeCanonicalType,
  stripNodeTypeVersion,
  unversionedFlowNodeType,
} from '../../utils/flowNodeCanonicalType';
import { CURIO_UNIVERSAL_NODE_TYPE, NodeType } from '../../constants';

describe('stripNodeTypeVersion', () => {
  test('strips a trailing @<digits> manifest version', () => {
    expect(stripNodeTypeVersion('curio.builtin/merge-flow@1')).toBe('curio.builtin/merge-flow');
    expect(stripNodeTypeVersion('pkg.author/custom-node@12')).toBe('pkg.author/custom-node');
  });

  test('leaves unversioned ids untouched', () => {
    expect(stripNodeTypeVersion('curio.builtin/merge-flow')).toBe('curio.builtin/merge-flow');
    expect(stripNodeTypeVersion('')).toBe('');
  });

  test('only strips the canonical <pkg>/<template>@<major> shape', () => {
    expect(stripNodeTypeVersion('a.pkg/tmpl@b@2')).toBe('a.pkg/tmpl@b@2'); // template ids cannot contain @
    expect(stripNodeTypeVersion('no-slash@2')).toBe('no-slash@2');
    expect(stripNodeTypeVersion('weird@')).toBe('weird@');
    expect(stripNodeTypeVersion('weird@abc')).toBe('weird@abc');
    expect(stripNodeTypeVersion('mid@1dle/x')).toBe('mid@1dle/x');
  });
});

describe('unversionedFlowNodeType', () => {
  test('the dev/64 regression: a versioned merge-flow node matches NodeType.MERGE_FLOW', () => {
    const node = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: 'curio.builtin/merge-flow@1' },
    };
    // The raw canonical type keeps the version (registry lookups need it) …
    expect(getFlowNodeCanonicalType(node)).toBe('curio.builtin/merge-flow@1');
    expect(getFlowNodeCanonicalType(node) === NodeType.MERGE_FLOW).toBe(false);
    // … while enum comparisons go through the unversioned helper.
    expect(unversionedFlowNodeType(node)).toBe(NodeType.MERGE_FLOW);
  });

  test('legacy unversioned specs keep matching', () => {
    const node = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: 'curio.builtin/merge-flow' },
    };
    expect(unversionedFlowNodeType(node)).toBe(NodeType.MERGE_FLOW);
  });

  test('non-universal nodes fall back to node.type, unversioned', () => {
    expect(unversionedFlowNodeType({ type: 'curio.builtin/data-pool@1' })).toBe(NodeType.DATA_POOL);
    expect(unversionedFlowNodeType({ type: undefined })).toBe('');
  });
});
