import { BoxType } from '../../constants';

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn() }),
}));

jest.mock('../../hook/useUTK', () => ({
  useUTK: () => ({
    sendCode: jest.fn(), defaultGrammar: '{}', showLoading: false,
    setSendCodeCallback: jest.fn(), customWidgetsCallback: jest.fn(),
    handleCompileGrammar: jest.fn(),
  }),
}));

jest.mock('../../hook/useTableData', () => ({
  __esModule: true,
  default: () => ({
    createTableData: jest.fn().mockReturnValue([]),
    parseOutputData: jest.fn().mockReturnValue({ newOutput: '', propagationObj: {} }),
    customWidgetsCallback: jest.fn(),
    processDataAsync: jest.fn().mockResolvedValue({ code: '', content: '' }),
    activeTab: '0', setActiveTab: jest.fn(), tabData: [],
  }),
}));

jest.mock('../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ boxExecProv: jest.fn() }),
}));

jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: '' } }),
}));

jest.mock('../../providers/TemplateProvider', () => ({
  useTemplateContext: () => ({ templates: [] }),
}));

jest.mock('reactflow', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useStoreApi: () => ({ subscribe: jest.fn().mockReturnValue(jest.fn()), getState: () => ({ edges: [] }) }),
  useEdges: () => [],
}));

import '../../registry/descriptors';
import { getAllNodeTypes, getNodeDescriptor } from '../../registry/nodeRegistry';

const ALL_BOX_TYPES = Object.values(BoxType).filter((v) => v !== BoxType.COMMENTS);

describe('Registered descriptors', () => {
  test('every BoxType (except COMMENTS) has a registered descriptor', () => {
    for (const bt of ALL_BOX_TYPES) {
      expect(() => getNodeDescriptor(bt)).not.toThrow();
    }
  });

  test('all descriptors have a valid adapter with handles array', () => {
    const descriptors = getAllNodeTypes();
    for (const desc of descriptors) {
      expect(desc.adapter).toBeDefined();
      expect(Array.isArray(desc.adapter.handles)).toBe(true);
    }
  });

  test('all descriptors have a useLifecycle function', () => {
    const descriptors = getAllNodeTypes();
    for (const desc of descriptors) {
      expect(typeof desc.adapter.useLifecycle).toBe('function');
    }
  });

  test('every descriptor has required metadata fields', () => {
    const descriptors = getAllNodeTypes();
    for (const desc of descriptors) {
      expect(desc.id).toBeTruthy();
      expect(desc.label).toBeTruthy();
      expect(desc.description).toBeTruthy();
      expect(desc.icon).toBeDefined();
      expect(['data', 'computation', 'vis_grammar', 'vis_simple', 'flow']).toContain(desc.category);
      expect(['code', 'widgets', 'grammar', 'none']).toContain(desc.editor);
    }
  });

  test('adapter.editor is EditorConfig or null for every descriptor', () => {
    const descriptors = getAllNodeTypes();
    for (const desc of descriptors) {
      if (desc.adapter.editor !== null) {
        expect(typeof desc.adapter.editor.code).toBe('boolean');
        expect(typeof desc.adapter.editor.grammar).toBe('boolean');
        expect(typeof desc.adapter.editor.widgets).toBe('boolean');
      }
    }
  });

  test('palette ordering is defined for inPalette descriptors', () => {
    const descriptors = getAllNodeTypes().filter((d) => d.inPalette);
    expect(descriptors.length).toBeGreaterThan(0);
    for (const desc of descriptors) {
      expect(desc.paletteOrder).toBeDefined();
    }
  });

  test('grammar boxes have grammarId set', () => {
    const grammarBoxes = getAllNodeTypes().filter((d) => d.category === 'vis_grammar');
    for (const desc of grammarBoxes) {
      expect(desc.grammarId).toBeTruthy();
    }
  });

  test('handles contain at least one entry for non-special box types', () => {
    const excluded = new Set([BoxType.MERGE_FLOW, BoxType.COMMENTS]);
    const descriptors = getAllNodeTypes().filter((d) => !excluded.has(d.id));
    for (const desc of descriptors) {
      expect(desc.adapter.handles.length).toBeGreaterThan(0);
    }
  });
});
