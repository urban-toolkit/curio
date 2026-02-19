import { Position } from 'reactflow';
import {
  standardInOut,
  outputOnly,
  inputOnly,
  withBidirectional,
  flowSwitchHandles,
} from '../../../adapters/box/handleHelpers';

describe('handleHelpers', () => {
  describe('standardInOut', () => {
    const handles = standardInOut();

    test('returns exactly 2 handles', () => {
      expect(handles).toHaveLength(2);
    });

    test('first handle is a left target with id "in"', () => {
      expect(handles[0]).toMatchObject({
        id: 'in',
        type: 'target',
        position: Position.Left,
      });
    });

    test('second handle is a right source with id "out"', () => {
      expect(handles[1]).toMatchObject({
        id: 'out',
        type: 'source',
        position: Position.Right,
      });
    });

    test('both handles have suggestion guard', () => {
      expect(handles[0].isConnectableOverride).toBeInstanceOf(Function);
      expect(handles[1].isConnectableOverride).toBeInstanceOf(Function);
    });
  });

  describe('outputOnly', () => {
    const handles = outputOnly();

    test('returns exactly 1 handle', () => {
      expect(handles).toHaveLength(1);
    });

    test('is a right source with id "out"', () => {
      expect(handles[0]).toMatchObject({
        id: 'out',
        type: 'source',
        position: Position.Right,
      });
    });
  });

  describe('inputOnly', () => {
    const handles = inputOnly();

    test('returns exactly 1 handle', () => {
      expect(handles).toHaveLength(1);
    });

    test('is a left target with id "in"', () => {
      expect(handles[0]).toMatchObject({
        id: 'in',
        type: 'target',
        position: Position.Left,
      });
    });
  });

  describe('withBidirectional', () => {
    test('appends a top source handle to the base array', () => {
      const base = standardInOut();
      const result = withBidirectional(base);

      expect(result).toHaveLength(3);
      expect(result[2]).toMatchObject({
        id: 'in/out',
        type: 'source',
        position: Position.Top,
      });
    });

    test('does not mutate the base array', () => {
      const base = standardInOut();
      const baseLengthBefore = base.length;
      withBidirectional(base);
      expect(base).toHaveLength(baseLengthBefore);
    });
  });

  describe('flowSwitchHandles', () => {
    const handles = flowSwitchHandles();

    test('returns exactly 3 handles', () => {
      expect(handles).toHaveLength(3);
    });

    test('has bottom target "in1", top target "in2", right source "out"', () => {
      expect(handles[0]).toMatchObject({ id: 'in1', type: 'target', position: Position.Bottom });
      expect(handles[1]).toMatchObject({ id: 'in2', type: 'target', position: Position.Top });
      expect(handles[2]).toMatchObject({ id: 'out', type: 'source', position: Position.Right });
    });
  });

  describe('suggestion guard', () => {
    test('allows connection when no suggestion type', () => {
      const handles = standardInOut();
      const guard = handles[0].isConnectableOverride!;

      expect(guard({ suggestionType: undefined }, true, [])).toBe(true);
      expect(guard({ suggestionType: 'none' }, true, [])).toBe(true);
    });

    test('blocks connection when suggestion type is set', () => {
      const handles = standardInOut();
      const guard = handles[0].isConnectableOverride!;

      expect(guard({ suggestionType: 'ai_suggested' }, true, [])).toBe(false);
    });

    test('blocks connection when isConnectable is false', () => {
      const handles = standardInOut();
      const guard = handles[0].isConnectableOverride!;

      expect(guard({ suggestionType: undefined }, false, [])).toBe(false);
    });
  });
});
