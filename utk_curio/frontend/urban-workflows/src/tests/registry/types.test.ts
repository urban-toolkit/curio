import { Position } from 'reactflow';
import type {
  BoxLifecycleHook,
  BoxLifecycleData,
  LifecycleResult,
  BoxAdapter,
  HandleDef,
  EditorConfig,
  ContainerConfig,
  UseBoxStateReturn,
} from '../../registry/types';

const mockBoxState = {
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
} as unknown as UseBoxStateReturn;

const mockData: BoxLifecycleData = {
  nodeId: 'test-node-1',
  nodeType: 'DATA_LOADING',
  outputCallback: jest.fn(),
  propagationCallback: jest.fn(),
  interactionsCallback: jest.fn(),
};

describe('BoxLifecycleHook contract', () => {
  test('a no-op lifecycle satisfies the contract', () => {
    const hook: BoxLifecycleHook = (_data, _boxState) => ({});
    const result = hook(mockData, mockBoxState);
    expect(result).toEqual({});
  });

  test('a lifecycle returning all fields satisfies the contract', () => {
    const hook: BoxLifecycleHook = (_data, _boxState) => ({
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

    const result = hook(mockData, mockBoxState);
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

describe('BoxLifecycleData', () => {
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

describe('BoxAdapter', () => {
  test('useLifecycle field accepts a BoxLifecycleHook', () => {
    const lifecycle: BoxLifecycleHook = () => ({});
    const adapter: BoxAdapter = {
      handles: [],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useLifecycle: lifecycle,
    };

    expect(adapter.useLifecycle).toBe(lifecycle);
    expect(adapter.useLifecycle(mockData, mockBoxState)).toEqual({});
  });

  test('editor can be null for non-editor boxes', () => {
    const adapter: BoxAdapter = {
      handles: [],
      editor: null,
      container: { noContent: true },
      useLifecycle: () => ({}),
    };
    expect(adapter.editor).toBeNull();
  });
});
