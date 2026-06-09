import {
  defaultSaveOutputDatasetFromEnv,
  readCurioEnvFlag,
} from '../../utils/curioEnvFlag';

describe('readCurioEnvFlag', () => {
  test('parses truthy and falsy strings', () => {
    expect(readCurioEnvFlag('1', false)).toBe(true);
    expect(readCurioEnvFlag('true', false)).toBe(true);
    expect(readCurioEnvFlag('0', true)).toBe(false);
    expect(readCurioEnvFlag('off', true)).toBe(false);
    expect(readCurioEnvFlag(undefined, true)).toBe(true);
    expect(readCurioEnvFlag('maybe', true)).toBe(true);
  });
});

describe('defaultSaveOutputDatasetFromEnv', () => {
  const prev = process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT;

  afterEach(() => {
    if (prev === undefined) {
      delete process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT;
    } else {
      process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT = prev;
    }
  });

  test('defaults to false when unset', () => {
    delete process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT;
    expect(defaultSaveOutputDatasetFromEnv()).toBe(false);
  });

  test('reads CURIO_DEFAULT_SAVE_NODE_OUTPUT', () => {
    process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT = '1';
    expect(defaultSaveOutputDatasetFromEnv()).toBe(true);
    process.env.CURIO_DEFAULT_SAVE_NODE_OUTPUT = 'false';
    expect(defaultSaveOutputDatasetFromEnv()).toBe(false);
  });
});
