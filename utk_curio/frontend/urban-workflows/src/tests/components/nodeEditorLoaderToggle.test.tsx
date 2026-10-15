/**
 * A loader's Code pill toggles its preview and its editor
 * (plans/data-loading-expressive-preview-memo.md, section 3.4). The pill shows
 * what a click shows: the code while previewing, an eye while editing. The
 * editor stays mounted under the preview.
 */
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

let mockDashboardOn = false;

jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ dashboardOn: mockDashboardOn }),
}));

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value }: any) => (
    <textarea data-testid="monaco" value={value ?? ''} readOnly />
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

jest.mock('../../components/editing/WidgetsEditor', () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock('../../components/editing/NodeProvenance', () => ({
  __esModule: true,
  default: () => null,
}));

import NodeEditor from '../../components/editing/NodeEditor';

const baseProps = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  data: { nodeId: 'n1', outputCallback: jest.fn() },
  output: { code: '', content: '' },
  nodeType: 'curio.builtin/data-loading',
  readOnly: false,
  applyGrammar: jest.fn(),
  code: true,
  grammar: false,
  widgets: false,
  defaultValue: 'df = curio_load_data("data.x.y")',
};

const loader = (over: Record<string, unknown> = {}) => ({
  view: 'preview' as const,
  canPreview: true,
  onToggle: jest.fn(),
  content: <div data-testid="preview">preview</div>,
  ...over,
});

const toggle = () => screen.getByTestId('loader-view-toggle');

afterEach(() => {
  mockDashboardOn = false;
});

describe('a loader in preview', () => {
  it('shows the preview over a hidden, still mounted editor, and offers the code', () => {
    render(<NodeEditor {...(baseProps as any)} loaderPreview={loader()} />);
    expect(screen.getByTestId('preview')).toBeTruthy();
    const editor = screen.getByTestId('monaco');
    expect(editor.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(toggle().getAttribute('aria-label')).toBe('Show code');
  });

  it('flips the view when its pill is clicked', () => {
    const props = loader();
    render(<NodeEditor {...(baseProps as any)} loaderPreview={props} />);
    fireEvent.click(toggle());
    expect(props.onToggle).toHaveBeenCalledTimes(1);
  });

  it('keeps the same editor across the switch', () => {
    const { rerender } = render(<NodeEditor {...(baseProps as any)} loaderPreview={loader()} />);
    const before = screen.getByTestId('monaco');
    rerender(<NodeEditor {...(baseProps as any)} loaderPreview={loader({ view: 'code' })} />);
    expect(screen.getByTestId('monaco')).toBe(before);
    expect(screen.queryByTestId('preview')).toBeNull();
  });
});

describe('a failed run that needs a library', () => {
  const failed = {
    code: 'error',
    content: "ModuleNotFoundError: No module named 'humanize'",
    missingModule: { module: 'humanize', distribution: 'humanize', installable: true, reason: null, detail: null },
  };

  it('offers the install under the preview, where the editor cannot be seen', () => {
    render(<NodeEditor {...(baseProps as any)} output={failed} loaderPreview={loader()} />);
    const slot = screen.getByTestId('loader-notice-slot');
    expect(within(slot).getByRole('button', { name: 'Install humanize' })).toBeTruthy();
  });

  it('offers it under the output again in code mode', () => {
    render(<NodeEditor {...(baseProps as any)} output={failed} loaderPreview={loader({ view: 'code' })} />);
    expect(screen.queryByTestId('loader-notice-slot')).toBeNull();
    expect(screen.getByRole('button', { name: 'Install humanize' })).toBeTruthy();
  });
});

describe('a loader in code mode', () => {
  it('offers the preview with an eye', () => {
    render(<NodeEditor {...(baseProps as any)} loaderPreview={loader({ view: 'code' })} />);
    expect(toggle().getAttribute('aria-label')).toBe('Show preview');
    expect(screen.getByTestId('monaco').closest('[aria-hidden="true"]')).toBeNull();
  });

  it('cannot preview an empty loader', () => {
    const props = loader({ view: 'code', canPreview: false });
    render(<NodeEditor {...(baseProps as any)} loaderPreview={props} />);
    expect(toggle().getAttribute('aria-label')).toBe('Write a loader to preview it');
    expect(toggle().getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(toggle());
    expect(props.onToggle).not.toHaveBeenCalled();
  });
});

describe('a node that is not a loader', () => {
  it('keeps the plain Code pill and no preview', () => {
    render(<NodeEditor {...(baseProps as any)} nodeType="curio.builtin/computation-analysis" />);
    expect(screen.queryByTestId('loader-view-toggle')).toBeNull();
    expect(screen.getByTestId('monaco').closest('[aria-hidden="true"]')).toBeNull();
  });
});
