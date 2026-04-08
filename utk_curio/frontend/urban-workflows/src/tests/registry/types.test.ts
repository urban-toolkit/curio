import { Position } from 'reactflow';
import type {
  NodeLifecycleHook,
  NodeLifecycleData,
  LifecycleResult,
  NodeAdapter,
  HandleDef,
  EditorConfig,
  ContainerConfig,
  UseNodeStateReturn,
} from '../../registry/types';

const mockNodeState = {
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
} as unknown as UseNodeStateReturn;

const mockData: NodeLifecycleData = {
  nodeId: 'test-node-1',
  nodeType: 'DATA_LOADING',
  outputCallback: jest.fn(),
  propagationCallback: jest.fn(),
  interactionsCallback: jest.fn(),
};

describe('NodeLifecycleHook contract', () => {
  test('a no-op lifecycle satisfies the contract', () => {
    const hook: NodeLifecycleHook = (_data, _nodeState) => ({});
    const result = hook(mockData, mockNodeState);
    expect(result).toEqual({});
  });

  test('a lifecycle returning all fields satisfies the contract', () => {
    const hook: NodeLifecycleHook = (_data, _nodeState) => ({
      applyGrammar: async () => {},
      customWidgetsCallback: () => {},
      defaultValueOverride: 'code here',
      sendCodeOverride: jest.fn(),
      setSendCodeCallbackOverride: jest.fn(),
      showLoading: true,
      contentComponent: null,
      setOutputCallbackOverride: jest.fn(),
      dynamicHandles: [{ id: 'dyn_0', type: 'target', position: Position.Left }],
    });

    const result = hook(mockData, mockNodeState);
    expect(result.applyGrammar).toBeInstanceOf(Function);
    expect(result.showLoading).toBe(true);
    expect(result.dynamicHandles).toHaveLength(1);
  });

  test('LifecycleResult fields are all optional', () => {
    const partial: LifecycleResult = { contentComponent: null };
    expect(partial.applyGrammar).toBeUndefined();
    expect(partial.showLoading).toBeUndefined();
    expect(partial.dynamicHandles).toBeUndefined();
  });
});

describe('NodeLifecycleData', () => {
  test('contains required INodeData fields', () => {
    expect(mockData.nodeId).toBe('test-node-1');
    expect(mockData.nodeType).toBe('DATA_LOADING');
  });

  test('contains runtime callbacks', () => {
    expect(typeof mockData.outputCallback).toBe('function');
    expect(typeof mockData.propagationCallback).toBe('function');
    expect(typeof mockData.interactionsCallback).toBe('function');
  });

  test('optional fields default to undefined', () => {
    expect(mockData.newPropagation).toBeUndefined();
    expect(mockData.suggestionType).toBeUndefined();
  });
});

describe('NodeAdapter', () => {
  test('useLifecycle field accepts a NodeLifecycleHook', () => {
    const lifecycle: NodeLifecycleHook = () => ({});
    const adapter: NodeAdapter = {
      handles: [],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useLifecycle: lifecycle,
    };

    expect(adapter.useLifecycle).toBe(lifecycle);
    expect(adapter.useLifecycle(mockData, mockNodeState)).toEqual({});
  });

  test('editor can be null for non-editor nodes', () => {
    const adapter: NodeAdapter = {
      handles: [],
      editor: null,
      container: { noContent: true },
      useLifecycle: () => ({}),
    };
    expect(adapter.editor).toBeNull();
  });
});
