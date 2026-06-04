import { resolveSaveOutputDataset } from '../../utils/saveOutputDataset';

describe('resolveSaveOutputDataset', () => {
  test('uses explicit defaultSave argument when node field unset', () => {
    expect(resolveSaveOutputDataset({}, false)).toBe(false);
    expect(resolveSaveOutputDataset({}, true)).toBe(true);
  });

  test('respects per-node override', () => {
    expect(resolveSaveOutputDataset({ saveOutputDataset: true })).toBe(true);
    expect(resolveSaveOutputDataset({ saveOutputDataset: false }, true)).toBe(false);
  });
});
