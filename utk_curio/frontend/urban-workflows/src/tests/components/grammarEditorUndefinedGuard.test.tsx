/**
 * Regression test for the second half of #157: GrammarEditor lacked the
 * `defaultValue != undefined` guard that CodeEditor has always had, so an
 * `undefined` defaultValue overwrote the editor's state with `undefined`. The
 * controlled `value` prop then snapped the model back on the next keystroke.
 *
 * Monaco is stubbed down to a textarea — the assertion is about which value the
 * component *hands* the editor, not about Monaco's rendering.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, onChange }: any) => (
    <textarea
      data-testid="monaco"
      value={value ?? '<<undefined>>'}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    enabled: false,
    connected: false,
    users: [],
    proposals: [],
    currentUserId: null,
    requestCodeChange: jest.fn(),
    approveCodeChange: jest.fn(),
    rejectCodeChange: jest.fn(),
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

import GrammarEditor from '../../components/editing/GrammarEditor';

const baseProps = {
  output: { code: '', content: '' } as any,
  nodeId: 'n1',
  schema: {},
  replacedCode: '',
  sendCodeToWidgets: jest.fn(),
  replacedCodeDirty: false,
  readOnly: false,
};

const SPEC = '{\n  "map": { "layerRefs": [] }\n}';

describe('GrammarEditor defaultValue handling', () => {
  test('adopts a real defaultValue that arrives after mount', () => {
    const { rerender } = render(<GrammarEditor {...baseProps} defaultValue={undefined} />);
    rerender(<GrammarEditor {...baseProps} defaultValue={SPEC} />);
    expect((screen.getByTestId('monaco') as HTMLTextAreaElement).value).toBe(SPEC);
  });

  test('an undefined defaultValue does not wipe the editor', () => {
    const { rerender } = render(<GrammarEditor {...baseProps} defaultValue={undefined} />);
    rerender(<GrammarEditor {...baseProps} defaultValue={SPEC} />);
    // The #157 loop drove defaultValue back to undefined on the very next render.
    rerender(<GrammarEditor {...baseProps} defaultValue={undefined} />);
    expect((screen.getByTestId('monaco') as HTMLTextAreaElement).value).toBe(SPEC);
  });
});
