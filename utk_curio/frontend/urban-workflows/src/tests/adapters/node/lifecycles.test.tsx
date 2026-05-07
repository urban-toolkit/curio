import React from 'react';
import { renderHook, act } from '@testing-library/react';
import type { NodeLifecycleHook, NodeLifecycleData, UseNodeStateReturn, LifecycleResult } from '../../../registry/types';

jest.setTimeout(15000);

jest.mock('../../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));

jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({
    nodeExecProv: jest.fn(),
    provenanceGraphNodes: {},
    provenanceGraphNodesRef: { current: {} },
    selectedParentExecRef: { current: {} },
    setSelectedExec: jest.fn(),
    loadNodeProvenance: jest.fn(),
    getAllNodeProvenance: jest.fn(() => ({})),
  }),
}));

jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'test-workflow' } }),
}));

jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('../../../services/api', () => ({
  fetchData: jest.fn().mockResolvedValue({ data: {}, dataType: 'dataframe' }),
}));

jest.mock('../../../components/editing/OutputContent', () => {
  const mockReact = require('react');
  return { __esModule: true, default: () => mockReact.createElement('div', null, 'output') };
});

jest.mock('reactflow', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useStoreApi: () => ({
    subscribe: jest.fn().mockReturnValue(jest.fn()),
    getState: () => ({ edges: [] }),
  }),
  useEdges: () => [],
}));

jest.mock('../../../providers/TemplateProvider', () => ({
  useTemplateContext: () => ({ templates: [] }),
}));

jest.mock('../../../utils/parsing', () => ({
  shortenString: (s: string) => s,
}));

jest.mock('../../../utils/formatters', () => ({
  formatDate: () => '2026-01-01',
  getType: () => ['dataframe'],
  mapTypes: (t: any) => t,
}));

jest.mock('@urban-toolkit/autk-map', () => ({ AutkMap: jest.fn() }), { virtual: true });
jest.mock('@urban-toolkit/autk-plot', () => ({ AutkPlot: jest.fn() }), { virtual: true });
jest.mock(
  '@urban-toolkit/autk-compute',
  () => ({ ComputeGpgpu: jest.fn(), ComputeRender: jest.fn() }),
  { virtual: true },
);

import { useCodeNodeLifecycle } from '../../../adapters/node/codeNodeLifecycle';
import { useDataExportLifecycle } from '../../../adapters/node/dataExportLifecycle';
import { useVegaLifecycle } from '../../../adapters/node/vegaLifecycle';
import { useSimpleVisLifecycle } from '../../../adapters/node/simpleVisLifecycle';
import { useFlowSwitchLifecycle } from '../../../adapters/node/flowSwitchLifecycle';
import { useMergeFlowLifecycle } from '../../../adapters/node/mergeFlowLifecycle';
import { useDataPoolLifecycle } from '../../../adapters/node/dataPoolLifecycle';
import { useAutkMapLifecycle } from '../../../adapters/node/autkMapLifecycle';
import { useAutkPlotLifecycle } from '../../../adapters/node/autkPlotLifecycle';
import { useAutkComputeLifecycle } from '../../../adapters/node/autkComputeLifecycle';
import { useAutkDbLifecycle } from '../../../adapters/node/autkDbLifecycle';

function makeMockData(overrides: Partial<NodeLifecycleData> = {}): NodeLifecycleData {
  return {
    nodeId: 'node-1',
    nodeType: 'DATA_LOADING',
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
    input: '',
    ...overrides,
  };
}

function makeMockNodeState(overrides: Partial<UseNodeStateReturn> = {}): UseNodeStateReturn {
  return {
    output: { code: '', content: '', outputType: '' },
    setOutput: jest.fn(),
    code: '',
    setCode: jest.fn(),
    sendCode: undefined,
    templateData: {},
    setTemplateData: jest.fn(),
    newTemplateFlag: false,
    showTemplateModal: false,
    showDescriptionModal: false,
    user: undefined,
    setTemplateConfig: jest.fn(),
    promptModal: jest.fn(),
    closeModal: jest.fn(),
    promptDescription: jest.fn(),
    closeDescription: jest.fn(),
    updateTemplate: jest.fn(),
    setSendCodeCallback: jest.fn(),
    ...overrides,
  } as unknown as UseNodeStateReturn;
}

const LIFECYCLE_RESULT_KEYS: (keyof LifecycleResult)[] = [
  'applyGrammar',
  'customWidgetsCallback',
  'defaultValueOverride',
  'sendCodeOverride',
  'setSendCodeCallbackOverride',
  'showLoading',
  'contentComponent',
  'setOutputCallbackOverride',
  'outputOverride',
  'disablePlay',
  'dynamicHandles',
  'outputOverride',
];

function assertValidLifecycleResult(result: LifecycleResult) {
  for (const key of Object.keys(result)) {
    expect(LIFECYCLE_RESULT_KEYS).toContain(key);
  }
}

async function callLifecycle(
  hook: NodeLifecycleHook,
  data?: Partial<NodeLifecycleData>,
  nodeState?: Partial<UseNodeStateReturn>,
) {
  const stableData = makeMockData(data);
  const stableNodeState = makeMockNodeState(nodeState);
  let hookResult: { current: LifecycleResult };
  await act(async () => {
    const rendered = renderHook(() =>
      hook(stableData, stableNodeState),
    );
    hookResult = rendered.result;
  });
  return hookResult!;
}

describe('Lifecycle hooks — NodeLifecycleHook contract conformance', () => {
  describe('useCodeNodeLifecycle', () => {
    test('returns empty lifecycle (output is inline in CodeEditor)', async () => {
      const result = await callLifecycle(useCodeNodeLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeUndefined();
    });
  });

  describe('useDataExportLifecycle', () => {
    test('returns expected fields', async () => {
      const result = await callLifecycle(useDataExportLifecycle);
      assertValidLifecycleResult(result.current);
      expect(typeof result.current.sendCodeOverride).toBe('function');
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
      expect(typeof result.current.customWidgetsCallback).toBe('function');
      expect(result.current.contentComponent).toBeDefined();
    });
  });

  describe('useVegaLifecycle', () => {
    test('returns applyGrammar', async () => {
      const result = await callLifecycle(useVegaLifecycle);
      assertValidLifecycleResult(result.current);
      expect(typeof result.current.applyGrammar).toBe('function');
    });
  });

  describe('useSimpleVisLifecycle', () => {
    test('renders table for tabular input', async () => {
      const result = await callLifecycle(useSimpleVisLifecycle, {
        input: { dataType: 'dataframe', data: {} } as any,
      });
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });

    test('renders image grid for image DataFrame input', async () => {
      const result = await callLifecycle(useSimpleVisLifecycle, {
        input: { dataType: 'dataframe', data: { image_id: {}, image_content: {} } } as any,
      });
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });

    test('returns no contentComponent for non-tabular input (text/value mode)', async () => {
      const result = await callLifecycle(useSimpleVisLifecycle, {
        input: { dataType: 'value', data: 42 } as any,
      });
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeUndefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });
  });

  describe('useFlowSwitchLifecycle', () => {
    test('returns empty object (no-op)', async () => {
      const result = await callLifecycle(useFlowSwitchLifecycle);
      assertValidLifecycleResult(result.current);
      expect(Object.keys(result.current)).toHaveLength(0);
    });
  });

  describe('useMergeFlowLifecycle', () => {
    test('returns dynamicHandles and setOutputCallbackOverride', async () => {
      const result = await callLifecycle(useMergeFlowLifecycle);
      assertValidLifecycleResult(result.current);
      expect(Array.isArray(result.current.dynamicHandles)).toBe(true);
      expect(result.current.dynamicHandles!.length).toBe(5);
      expect(typeof result.current.setOutputCallbackOverride).toBe('function');
    });

    test('dynamic handles have correct ids and positions', async () => {
      const result = await callLifecycle(useMergeFlowLifecycle);
      const handles = result.current.dynamicHandles!;

      handles.forEach((h, i) => {
        expect(h.id).toBe(`in_${i}`);
        expect(h.type).toBe('target');
        expect(h.position).toBe('left');
      });
    });
  });

  describe('useDataPoolLifecycle', () => {
    test('returns contentComponent, customWidgetsCallback, overrides', async () => {
      const result = await callLifecycle(useDataPoolLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.customWidgetsCallback).toBe('function');
      expect(typeof result.current.setOutputCallbackOverride).toBe('function');
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });
  });

  describe('useAutkMapLifecycle', () => {
    test('returns canvas contentComponent, default code, and sendCodeOverride', async () => {
      const result = await callLifecycle(useAutkMapLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.defaultValueOverride).toBe('string');
      expect(result.current.defaultValueOverride).toContain('AutkMap');
      expect(typeof result.current.sendCodeOverride).toBe('function');
    });

    test('omits defaultValueOverride when node already has code', async () => {
      const result = await callLifecycle(useAutkMapLifecycle, {
        defaultCode: 'const map = new AutkMap(container);',
      } as any);
      assertValidLifecycleResult(result.current);
      expect(result.current.defaultValueOverride).toBeUndefined();
    });
  });

  describe('useAutkPlotLifecycle', () => {
    test('returns div contentComponent, default code, and sendCodeOverride', async () => {
      const result = await callLifecycle(useAutkPlotLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.defaultValueOverride).toBe('string');
      expect(result.current.defaultValueOverride).toContain('AutkPlot');
      expect(typeof result.current.sendCodeOverride).toBe('function');
    });
  });

  describe('useAutkComputeLifecycle', () => {
    test('returns hidden contentComponent, default code, and sendCodeOverride', async () => {
      const result = await callLifecycle(useAutkComputeLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.defaultValueOverride).toBe('string');
      expect(typeof result.current.sendCodeOverride).toBe('function');
    });
  });

  describe('useAutkDbLifecycle', () => {
    test('seeds default code on a fresh palette drop', async () => {
      const result = await callLifecycle(useAutkDbLifecycle);
      assertValidLifecycleResult(result.current);
      expect(typeof result.current.defaultValueOverride).toBe('string');
      expect(result.current.defaultValueOverride).toContain('AutkSpatialDb');
    });

    test('returns no override when example or saved code already exists', async () => {
      const result = await callLifecycle(useAutkDbLifecycle, {
        defaultCode: 'await db.init();',
      } as any);
      assertValidLifecycleResult(result.current);
      expect(result.current.defaultValueOverride).toBeUndefined();
    });
  });
});
