/**
 * Guard test for the #159 / #169 class of bug: a lookup keyed by the UNVERSIONED
 * `NodeType` enum, fed the VERSIONED id a palette drag actually produces.
 *
 * Both forms coexist in real canvases — a palette drag stores
 * `curio.builtin/merge-flow@1`, the Jupyter converter and legacy trills store
 * `curio.builtin/merge-flow` — and nothing normalizes them at load time. So
 * every unversioned-keyed map has to be read through a normalizer, or versioned
 * nodes silently take the fallback branch.
 *
 * This is deliberately a *parity* test rather than a test of one call site: it
 * asserts the two forms are indistinguishable to each lookup, which is the
 * property that keeps getting broken one call site at a time.
 */
import { NodeType, CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';
import {
  unversionedNodeType,
  getUnversionedFlowNodeType,
  getFlowNodeCanonicalType,
} from '../../utils/flowNodeCanonicalType';

const ALL_TYPES = Object.values(NodeType);
const versioned = (t: string, major = 1) => `${t}@${major}`;

describe('unversionedNodeType', () => {
  test.each(ALL_TYPES)('strips @major from %s', (type) => {
    expect(unversionedNodeType(versioned(type))).toBe(type);
    expect(unversionedNodeType(versioned(type, 7))).toBe(type);
  });

  test('leaves an already-unversioned id untouched', () => {
    ALL_TYPES.forEach((type) => expect(unversionedNodeType(type)).toBe(type));
  });

  test('leaves a non-canonical string untouched rather than mangling it', () => {
    // Not `<pkg>/<template>@<major>`, so there is no version to strip.
    expect(unversionedNodeType('__curioUniversalNode')).toBe('__curioUniversalNode');
    expect(unversionedNodeType('')).toBe('');
  });
});

describe('getUnversionedFlowNodeType', () => {
  test.each(ALL_TYPES)('normalizes both id forms of %s to the enum value', (type) => {
    // Shape of a real canvas node: RF `type` is the stable sentinel and the
    // dispatcher id lives in `data.nodeType` (see getFlowNodeCanonicalType).
    const bare = { type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType: type } };
    const withVersion = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: versioned(type) },
    };

    expect(getUnversionedFlowNodeType(bare)).toBe(type);
    expect(getUnversionedFlowNodeType(withVersion)).toBe(type);
    // The un-normalized helper is what the buggy call sites used: it hands back
    // the `@1` verbatim, which is why `=== NodeType.X` failed.
    expect(getFlowNodeCanonicalType(withVersion)).toBe(versioned(type));
  });
});

describe('colour maps resolve both id forms', () => {
  // Both maps are static mirrors of the built-in package keyed by unversioned
  // ids. A versioned miss is not a crash, it is a silently grey node — exactly
  // the kind of regression a type check cannot catch.
  const COLOURED: NodeType[] = [
    NodeType.DATA_LOADING,
    NodeType.DATA_TRANSFORMATION,
    NodeType.MERGE_FLOW,
    NodeType.DATA_POOL,
    NodeType.VIS_VEGA,
  ];

  test.each(COLOURED)('DataflowThumbnail gives %s the same colour either way', (type) => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { __testables } = require('../../components/DataflowThumbnail');
    const { NODE_COLORS, FALLBACK_COLOR, unversionedType } = __testables;

    const bare = NODE_COLORS[unversionedType(type)] ?? FALLBACK_COLOR;
    const withVersion = NODE_COLORS[unversionedType(versioned(type))] ?? FALLBACK_COLOR;

    expect(bare).not.toBe(FALLBACK_COLOR);
    expect(withVersion).toBe(bare);
  });
});
