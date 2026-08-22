import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';
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
