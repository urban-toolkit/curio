/**
 * Regression test for #153 — Delete did not remove selected canvas elements.
 *
 * MainCanvas passed `deleteKeyCode={isSharedView ? null : undefined}`, and
 * `undefined` means "use the React Flow default", which is `'Backspace'` alone.
 * macOS hid the bug (its delete key emits Backspace); on Windows the Delete key
 * simply did nothing.
 *
 * Asserting the prop rather than simulating a keypress is deliberate: the
 * key->delete wiring is React Flow's own, already covered by its tests, and the
 * only thing Curio controls (and the only thing that regressed) is this prop.
 * The keyboard behaviour itself is covered end-to-end in
 * test_frontend/test_canvas_delete_key_e2e.py.
 */
import { DEFAULT_DELETE_KEY_CODES } from '../../components/canvasKeyBindings';

describe('canvas delete key codes', () => {
  test('binds Delete as well as Backspace', () => {
    expect(DEFAULT_DELETE_KEY_CODES).toEqual(['Backspace', 'Delete']);
  });

  test('is an array, which is how React Flow expresses alternatives', () => {
    // A string would be a single binding, and `'Backspace+Delete'` would be read
    // as a chord (React Flow uses '+' as the combo separator), not as either key.
    expect(Array.isArray(DEFAULT_DELETE_KEY_CODES)).toBe(true);
    DEFAULT_DELETE_KEY_CODES.forEach((k) => expect(k).not.toContain('+'));
  });
});
