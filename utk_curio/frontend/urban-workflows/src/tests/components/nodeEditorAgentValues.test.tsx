/**
 * An agent's applied change to a node's widget values
 * (`node.settings.write`) reaches the node's own setter, the one a value set
 * in its Widgets tab goes through: the value lands in the node, the node is
 * out of date, the dataflow Unsaved, and an automatic run takes the node when
 * automatic runs are on. A node without a Widgets tab registers no setter.
 *
 * WidgetsEditor is stubbed: the setter is NodeEditor's, and the tab's own
 * controls are their own concern.
 */
import React from 'react';
import { render, act } from '@testing-library/react';

const mockMarkNodeStale = jest.fn();
const mockMarkDirty = jest.fn();
const mockRequestAutoRun = jest.fn();
jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markNodeStale: mockMarkNodeStale,
    markDirty: mockMarkDirty,
    requestAutoRun: mockRequestAutoRun,
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

jest.mock('../../components/editing/WidgetsEditor', () => ({
  __esModule: true,
  default: () => null,
}));

import NodeEditor from '../../components/editing/NodeEditor';
import { writeNodeSettings } from '../../utils/nodeSettingsWriters';

const COMBINE = {
  name: 'combine', type: 'choice', label: 'Combine', default: 'mean',
  options: { choices: ['mean', 'sum', 'max'] },
};
const THRESHOLD = { name: 'threshold', type: 'slider', default: 2, options: { min: 0, max: 10 } };

/** A Python node holding two widgets, with its Widgets tab or without. */
function renderEditor(widgetsTab: boolean) {
  const data: any = { nodeId: 'chart', outputCallback: jest.fn(), widgets: [{ ...COMBINE }, { ...THRESHOLD }] };
  render(
    <NodeEditor
      setSendCodeCallback={jest.fn()}
      setOutputCallback={jest.fn()}
      data={data}
      output={{ code: '', content: '' }}
      nodeType={'curio.builtin/computation-analysis'}
      readOnly={false}
      applyGrammar={jest.fn()}
      code={true}
      grammar={false}
      widgets={widgetsTab}
      defaultValue={"return input_0.groupby('tract')['shadow'].agg([!! combine !!])\n"}
    />,
  );
  const fallback = jest.fn();
  const write = (values: Record<string, unknown>) =>
    act(() => writeNodeSettings({ nodes: () => [{ id: 'chart', data }], updateDataNode: fallback }, 'chart', { widgets: values }));
  return { data, write, fallback };
}

beforeEach(() => {
  mockMarkNodeStale.mockReset();
  mockMarkDirty.mockReset();
  mockRequestAutoRun.mockReset();
});

test("an agent's value lands in the node as one set in its Widgets tab: out of date, Unsaved, and run when automatic runs are on", () => {
  const { data, write, fallback } = renderEditor(true);
  write({ combine: 'max' });
  expect(fallback).not.toHaveBeenCalled();
  const byName = Object.fromEntries(data.widgets.map((w: any) => [w.name, w]));
  expect(byName.combine.value).toBe('max');
  expect(byName.threshold.value).toBeUndefined();
  expect(mockMarkNodeStale).toHaveBeenCalledWith('chart');
  expect(mockMarkDirty).toHaveBeenCalled();
  expect(mockRequestAutoRun).toHaveBeenCalledWith(['chart']);
});

test('a node without a Widgets tab registers no setter, so its values go into its data', () => {
  const { write, fallback } = renderEditor(false);
  write({ combine: 'max' });
  expect(fallback).toHaveBeenCalledTimes(1);
  expect(fallback.mock.calls[0][1].widgets.find((w: any) => w.name === 'combine').value).toBe('max');
});
