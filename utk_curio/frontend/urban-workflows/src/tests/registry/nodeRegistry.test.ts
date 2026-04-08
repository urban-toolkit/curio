import { NodeType, SupportedType } from '../../constants';
import {
  registerNode,
  getNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
} from '../../registry/nodeRegistry';
import { NodeDescriptor, NodeLifecycleHook } from '../../registry/types';
import { faCircle } from '@fortawesome/free-solid-svg-icons';
import { Position } from 'reactflow';

const noopLifecycle: NodeLifecycleHook = () => ({});

function makeDescriptor(overrides: Partial<NodeDescriptor> = {}): NodeDescriptor {
  return {
    id: NodeType.DATA_LOADING,
    category: 'data',
    label: 'Test Node',
    icon: faCircle,
    inputPorts: [],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: 'code',
    inPalette: true,
    paletteOrder: 1,
    description: 'A test node',
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [{ id: 'out', type: 'source', position: Position.Right }],
      editor: { code: true, grammar: false, widgets: false },
      container: {},
      useLifecycle: noopLifecycle,
    },
    ...overrides,
  };
}

describe('nodeRegistry', () => {
  describe('registerNode + getNodeDescriptor', () => {
    test('registers and retrieves a descriptor by NodeType', () => {
      const desc = makeDescriptor({ id: NodeType.DATA_LOADING });
      registerNode(desc);

      const result = getNodeDescriptor(NodeType.DATA_LOADING);
      expect(result).toBe(desc);
      expect(result.id).toBe(NodeType.DATA_LOADING);
      expect(result.label).toBe('Test Node');
    });

    test('throws for unregistered NodeType', () => {
      expect(() => getNodeDescriptor('NONEXISTENT' as NodeType)).toThrow(
        /No descriptor registered for NodeType/,
      );
    });

    test('overwrites duplicate registration with warning', () => {
      const warnSpy = jest.spyOn(console, 'warn').mockImplementation();

      const first = makeDescriptor({ id: NodeType.CONSTANTS, label: 'First' });
      const second = makeDescriptor({ id: NodeType.CONSTANTS, label: 'Second' });

      registerNode(first);
      registerNode(second);

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('CONSTANTS'),
      );
      expect(getNodeDescriptor(NodeType.CONSTANTS).label).toBe('Second');

      warnSpy.mockRestore();
    });
  });

  describe('getAllNodeTypes', () => {
    test('returns all registered descriptors', () => {
      const all = getAllNodeTypes();
      expect(all.length).toBeGreaterThanOrEqual(1);
      expect(all.every((d) => d.id !== undefined)).toBe(true);
    });
  });

  describe('getPaletteNodeTypes', () => {
    test('returns only inPalette descriptors sorted by paletteOrder', () => {
      registerNode(makeDescriptor({
        id: NodeType.DATA_CLEANING,
        inPalette: true,
        paletteOrder: 99,
        label: 'Z-Last',
      }));
      registerNode(makeDescriptor({
        id: NodeType.VIS_TEXT,
        inPalette: false,
        label: 'Hidden',
      }));

      const palette = getPaletteNodeTypes();
      expect(palette.every((d) => d.inPalette)).toBe(true);
      expect(palette.find((d) => d.id === NodeType.VIS_TEXT)).toBeUndefined();

      for (let i = 1; i < palette.length; i++) {
        expect((palette[i - 1].paletteOrder ?? 999))
          .toBeLessThanOrEqual(palette[i].paletteOrder ?? 999);
      }
    });
  });
});
