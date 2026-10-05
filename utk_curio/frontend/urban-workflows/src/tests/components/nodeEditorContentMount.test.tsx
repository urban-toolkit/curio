/**
 * A content node's output (an Autark map or plot, a Data Pool table, ...)
 * fills its pane, as a Vega-Lite chart's does (#631, #668).
 *
 * The node body keeps every pane clear of the port markers
 * (nodeEditorPanesInBody.test.tsx), so the mount adds no inset of its own.
 * The Vega mount's half of this contract is in nodeEditorOutputScroll.test.tsx.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

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
  nodeType: 'curio.builtin/data-pool',
  readOnly: false,
  applyGrammar: jest.fn(),
  // Required by NodeEditorProps; none of them matter to this file, which is
  // about the output pane's geometry.
  code: true,
  grammar: false,
  widgets: false,
  defaultValue: '',
  // What an Autark map, a Data Pool or a Simple View hands NodeEditor in
  // place of an outputId.
  contentComponent: <div data-testid="content" />,
};

function mount(): HTMLElement {
  const el = screen.getByTestId('content').parentElement;
  if (!el) throw new Error('the content component has no parent');
  return el;
}

afterEach(() => {
  mockDashboardOn = false;
});

describe("a content node's output mount", () => {
  test.each([
    ['on the canvas', false],
    ['on a dashboard tile', true],
  ])('fills its pane %s, with no inset of its own', (_, dashboardOn) => {
    mockDashboardOn = dashboardOn;
    render(<NodeEditor {...baseProps} />);
    const el = mount();
    expect(el.style.height).toBe('100%');
    expect(el.style.width).toBe('');
    expect(el.style.marginLeft).toBe('');
    expect(el.style.marginRight).toBe('');
  });

  test('leaves alignment and scrolling to the content component', () => {
    // The Vega mount centres its chart and scrolls it; a table or a map body
    // does both its own way, so the content mount must not.
    render(<NodeEditor {...baseProps} />);
    const el = mount();
    expect(el).toHaveClass('curio-content-mount');
    expect(el.style.textAlign).toBe('');
    expect(el.style.overflow).toBe('');
  });

  test('sits in the clamped output pane', () => {
    render(<NodeEditor {...baseProps} />);
    const pane = mount().parentElement as HTMLElement;
    expect(pane).toHaveClass('tab-pane');
    expect(pane.style.overflow).toBe('hidden');
  });
});
