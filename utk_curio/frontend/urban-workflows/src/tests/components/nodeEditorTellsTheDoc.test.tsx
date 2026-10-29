/**
 * A widget's value and a selection tag, set on a node's Widgets tab, are
 * written into the node's data in place (`NodeEditor`), so the canvas sees no
 * new node. The editor tells the dataflow's doc (`dataflowDoc.noteNodeData`),
 * which then writes them: every other tab, a run on the server and a reopen
 * get them.
 *
 * WidgetsEditor is stubbed: what it hands back through `onWidgetsChange` and
 * `onSelectionsChange` is what is under test, as in
 * nodeEditorWidgetBridge.test.tsx.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

const mockNoteNodeData = jest.fn();
jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markDirty: jest.fn(),
    markNodeStale: jest.fn(),
    requestAutoRun: jest.fn(),
    dataflowDoc: { noteNodeData: mockNoteNodeData },
  }),
}));

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value }: any) => (
    <textarea data-testid="monaco" value={value ?? ''} readOnly />
  ),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

/** The props NodeEditor last handed the Widgets tab. */
let mockWidgetsProps: any = null;
jest.mock('../../components/editing/WidgetsEditor', () => ({
  __esModule: true,
  default: (props: any) => {
    mockWidgetsProps = props;
    return <div data-testid="widgets" />;
  },
}));

import NodeEditor from '../../components/editing/NodeEditor';

const props = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  output: { code: '', content: '' },
  nodeType: 'curio.builtin/computation-analysis',
  readOnly: false,
  applyGrammar: jest.fn(),
  contentComponent: <div />,
  code: true,
  grammar: false,
  widgets: true,
  defaultValue: 'x = 1\n',
};

beforeEach(() => {
  mockNoteNodeData.mockClear();
  mockWidgetsProps = null;
});

test("a widget's value set on the Widgets tab is written in place, and the doc is told", () => {
  const data: any = { nodeId: 'n1', outputCallback: jest.fn(), widgets: [{ name: 'rows', type: 'number', default: 5 }] };
  render(<NodeEditor {...(props as any)} data={data} />);
  expect(mockWidgetsProps).not.toBeNull();

  act(() => mockWidgetsProps.onWidgetsChange([{ name: 'rows', type: 'number', default: 5, value: 9 }]));

  expect(data.widgets).toEqual([{ name: 'rows', type: 'number', default: 5, value: 9 }]);
  expect(mockNoteNodeData).toHaveBeenCalledWith('n1');
});

test('a selection tag set on the Widgets tab is written in place, and the doc is told', () => {
  const data: any = { nodeId: 'n1', outputCallback: jest.fn(), widgets: [] };
  render(<NodeEditor {...(props as any)} data={data} />);
  expect(mockWidgetsProps).not.toBeNull();
  const tag = { name: 'picked', node: 'chart', column: 'id', ids: [1, 2] };

  act(() => mockWidgetsProps.onSelectionsChange([tag]));

  expect(data.selections).toEqual([tag]);
  expect(mockNoteNodeData).toHaveBeenCalledWith('n1');
});
