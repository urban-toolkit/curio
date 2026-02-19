import { BoxType, SupportedType } from '../../constants';
import {
  registerNode,
  getNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
} from '../../registry/nodeRegistry';
import { BoxDescriptor, BoxLifecycleHook } from '../../registry/types';
import { faCircle } from '@fortawesome/free-solid-svg-icons';
import { Position } from 'reactflow';

const noopLifecycle: BoxLifecycleHook = () => ({});

function makeDescriptor(overrides: Partial<BoxDescriptor> = {}): BoxDescriptor {
  return {
    id: BoxType.DATA_LOADING,
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
    test('registers and retrieves a descriptor by BoxType', () => {
      const desc = makeDescriptor({ id: BoxType.DATA_LOADING });
      registerNode(desc);

      const result = getNodeDescriptor(BoxType.DATA_LOADING);
      expect(result).toBe(desc);
      expect(result.id).toBe(BoxType.DATA_LOADING);
      expect(result.label).toBe('Test Node');
    });

    test('throws for unregistered BoxType', () => {
      expect(() => getNodeDescriptor('NONEXISTENT' as BoxType)).toThrow(
        /No descriptor registered for BoxType/,
      );
    });

    test('overwrites duplicate registration with warning', () => {
      const warnSpy = jest.spyOn(console, 'warn').mockImplementation();

      const first = makeDescriptor({ id: BoxType.CONSTANTS, label: 'First' });
      const second = makeDescriptor({ id: BoxType.CONSTANTS, label: 'Second' });

      registerNode(first);
      registerNode(second);

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('CONSTANTS'),
      );
      expect(getNodeDescriptor(BoxType.CONSTANTS).label).toBe('Second');

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
        id: BoxType.DATA_CLEANING,
        inPalette: true,
        paletteOrder: 99,
        label: 'Z-Last',
      }));
      registerNode(makeDescriptor({
        id: BoxType.VIS_TEXT,
        inPalette: false,
        label: 'Hidden',
      }));

      const palette = getPaletteNodeTypes();
      expect(palette.every((d) => d.inPalette)).toBe(true);
      expect(palette.find((d) => d.id === BoxType.VIS_TEXT)).toBeUndefined();

      for (let i = 1; i < palette.length; i++) {
        expect((palette[i - 1].paletteOrder ?? 999))
          .toBeLessThanOrEqual(palette[i].paletteOrder ?? 999);
      }
    });
  });
});
