/**
 * Canvas keyboard bindings.
 *
 * Extracted so they can be asserted directly: MainCanvas pulls in the whole
 * editor/registry/vega module graph, which is far too much to mount just to
 * check a key list.
 */

/**
 * Keys that delete the current canvas selection.
 *
 * React Flow's own default is `'Backspace'` only, which left Windows users with
 * a dead Delete key (#153). `useKeyPress` treats each array entry as an
 * independent binding and early-returns on `isInputDOMNode`, so neither key can
 * fire while the caret is in Monaco or a text input.
 */
export const DEFAULT_DELETE_KEY_CODES: string[] = ['Backspace', 'Delete'];
