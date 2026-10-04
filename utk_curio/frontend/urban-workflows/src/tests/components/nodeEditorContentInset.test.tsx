/**
 * A content node's output stays clear of the port markers, as a Vega-Lite
 * chart's does (#631).
 *
 * The markers are 17 px boxes at the node's edges, over its 5 px padding, so
 * each covers 12 px of the output pane. #522 inset the Vega mount by
 * PORT_MARKER_INSET; an Autark map or plot, a Data Pool table and the other
 * content components were drawn straight into the pane, under the markers.
 *
 * The geometry half of the Vega mount's contract is in
 * nodeEditorOutputScroll.test.tsx; this is the same contract for
 * `contentComponent`.
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
  test('stays clear of the port markers at both edges', () => {
    render(<NodeEditor {...baseProps} inputMarker outputMarker />);
    const el = mount();
    expect(el.style.marginLeft).toBe('14px');
    expect(el.style.marginRight).toBe('14px');
    expect(el.style.width).toBe('calc(100% - 28px)');
    expect(el.style.height).toBe('100%');
  });

  test('insets only the side that has a marker', () => {
    render(<NodeEditor {...baseProps} outputMarker />);
    const el = mount();
    expect(el.style.marginLeft).toBe('0px');
    expect(el.style.marginRight).toBe('14px');
    expect(el.style.width).toBe('calc(100% - 14px)');
  });

  test('fills a dashboard tile, which shows no markers', () => {
    mockDashboardOn = true;
    render(<NodeEditor {...baseProps} inputMarker outputMarker />);
    const el = mount();
    expect(el.style.marginLeft).toBe('0px');
    expect(el.style.marginRight).toBe('0px');
    expect(el.style.width).toBe('100%');
  });

  test('leaves alignment and scrolling to the content component', () => {
    // The Vega mount centres its chart and scrolls it; a table or a map body
    // does both its own way, so the content mount must not.
    render(<NodeEditor {...baseProps} inputMarker outputMarker />);
    const el = mount();
    expect(el).toHaveClass('curio-content-mount');
    expect(el.style.textAlign).toBe('');
    expect(el.style.overflow).toBe('');
  });

  test('sits in the clamped output pane', () => {
    render(<NodeEditor {...baseProps} inputMarker outputMarker />);
    const pane = mount().parentElement as HTMLElement;
    expect(pane).toHaveClass('tab-pane');
    expect(pane.style.overflow).toBe('hidden');
  });
});
