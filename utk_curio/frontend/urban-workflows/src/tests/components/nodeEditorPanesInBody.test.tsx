/**
 * Every pane of a node's editor stays in the node body, clear of the port
 * markers (#668).
 *
 * NodeContainer's body is 15 px in from each side of the node, further than
 * the markers reach. NodeEditor laid its panes out in a Bootstrap row, whose
 * negative gutter margins pulled them 12 px back out, under the markers: a
 * code node's first line ran under its output marker.
 *
 * jsdom has no Bootstrap CSS, so this checks the cause; the geometry on a real
 * node is `assert_editor_panes_clear_of_markers` in the e2e node execution
 * test, run on every example dataflow.
 */
import React from 'react';
import { render } from '@testing-library/react';

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
  defaultValue: '',
};

// A code node, a Vega-Lite node's output and a content node's output (an
// Autark map, a Data Pool table): all of them share NodeEditor's Tab.Content.
const editors: [string, Record<string, unknown>][] = [
  ['a code node', {}],
  ['a Vega-Lite output', { nodeType: 'curio.builtin/vis-vega', outputId: 'vega-n1' }],
  ['a content output', { nodeType: 'curio.builtin/data-pool', contentComponent: <div /> }],
];

/** The Bootstrap rows between the editor's root and its panes that keep a gutter. */
function gutterRowsAroundPanes(container: HTMLElement): string[] {
  const panes = container.querySelector('.tab-content');
  if (!panes) throw new Error('NodeEditor rendered no .tab-content');
  const rows: string[] = [];
  for (let el = panes.parentElement; el && el !== container; el = el.parentElement) {
    if (el.classList.contains('row') && !el.classList.contains('g-0')) rows.push(el.className);
  }
  return rows;
}

afterEach(() => {
  mockDashboardOn = false;
});

describe("a node editor's panes", () => {
  test.each(editors)('in %s, no row gutter pulls them out of the node body', (_, props) => {
    const { container } = render(<NodeEditor {...baseProps} {...props} />);
    expect(gutterRowsAroundPanes(container)).toEqual([]);
  });

  test('stay in the body of a dashboard tile too', () => {
    mockDashboardOn = true;
    const { container } = render(
      <NodeEditor {...baseProps} nodeType="curio.builtin/vis-vega" outputId="vega-n1" />,
    );
    expect(gutterRowsAroundPanes(container)).toEqual([]);
  });
});
