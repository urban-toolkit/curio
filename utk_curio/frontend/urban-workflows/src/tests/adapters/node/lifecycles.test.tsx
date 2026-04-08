import React from 'react';
import { renderHook, act } from '@testing-library/react';
import type { NodeLifecycleHook, NodeLifecycleData, UseNodeStateReturn, LifecycleResult } from '../../../registry/types';

jest.setTimeout(15000);

jest.mock('../../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));

jest.mock('../../../hook/useUTK', () => ({
  useUTK: () => ({
    sendCode: jest.fn(),
    defaultGrammar: '{}',
    showLoading: false,
    setSendCodeCallback: jest.fn(),
    customWidgetsCallback: jest.fn(),
    handleCompileGrammar: jest.fn().mockResolvedValue(undefined),
  }),
}));

jest.mock('../../../hook/useTableData', () => ({
  __esModule: true,
  default: () => ({
    createTableData: jest.fn().mockReturnValue([]),
    parseOutputData: jest.fn().mockReturnValue({ newOutput: '', propagationObj: {} }),
    customWidgetsCallback: jest.fn(),
    processDataAsync: jest.fn().mockResolvedValue({ code: '', content: '' }),
    activeTab: '0',
    setActiveTab: jest.fn(),
    tabData: [],
  }),
}));

jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));

jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'test-workflow' } }),
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

import { useCodeNodeLifecycle } from '../../../adapters/node/codeNodeLifecycle';
import { useDataExportLifecycle } from '../../../adapters/node/dataExportLifecycle';
import { useVegaLifecycle } from '../../../adapters/node/vegaLifecycle';
import { useUtkLifecycle } from '../../../adapters/node/utkLifecycle';
import { useTableLifecycle } from '../../../adapters/node/tableLifecycle';
import { useImageLifecycle } from '../../../adapters/node/imageLifecycle';
import { useTextLifecycle } from '../../../adapters/node/textLifecycle';
import { useFlowSwitchLifecycle } from '../../../adapters/node/flowSwitchLifecycle';
import { useMergeFlowLifecycle } from '../../../adapters/node/mergeFlowLifecycle';
import { useDataPoolLifecycle } from '../../../adapters/node/dataPoolLifecycle';

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
    test('returns contentComponent only', async () => {
      const result = await callLifecycle(useCodeNodeLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
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

  describe('useUtkLifecycle', () => {
    test('returns full grammar lifecycle fields', async () => {
      const result = await callLifecycle(useUtkLifecycle);
      assertValidLifecycleResult(result.current);
      expect(typeof result.current.applyGrammar).toBe('function');
      expect(result.current.sendCodeOverride).toBeDefined();
      expect(result.current.setSendCodeCallbackOverride).toBeDefined();
      expect(typeof result.current.showLoading).toBe('boolean');
      expect(typeof result.current.customWidgetsCallback).toBe('function');
      expect(result.current.defaultValueOverride).toBeDefined();
    });
  });

  describe('useTableLifecycle', () => {
    test('returns contentComponent and setSendCodeCallbackOverride', async () => {
      const result = await callLifecycle(useTableLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });
  });

  describe('useImageLifecycle', () => {
    test('returns contentComponent and setSendCodeCallbackOverride', async () => {
      const result = await callLifecycle(useImageLifecycle);
      assertValidLifecycleResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });
  });

  describe('useTextLifecycle', () => {
    test('returns empty object (no-op)', async () => {
      const result = await callLifecycle(useTextLifecycle);
      assertValidLifecycleResult(result.current);
      expect(Object.keys(result.current)).toHaveLength(0);
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
});
