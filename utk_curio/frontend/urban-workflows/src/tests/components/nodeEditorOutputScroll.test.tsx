/**
 * The Vega mount container scrolls, and does not zoom the canvas (#202).
 *
 * A Vega canvas is sized in CSS px from the compiled spec, so anything taller
 * than the output pane was simply cut off: the pane is `overflow: hidden` and
 * the `<div id={outputId}>` inside it was `height: 100%` with the default
 * `overflow: visible` and no `nowheel`.
 *
 * The `nowheel` assertion is the load-bearing one. An overflow-only fix looks
 * correct in a screenshot and regresses in use: React Flow's ZoomPane swallows
 * the wheel event before the div sees it, so scrolling the chart zooms the
 * whole canvas instead. `nodrag` stays for the same family of reasons — a drag
 * inside the chart must not move the node.
 *
 * The other half of #202 — that multi-view specs must keep their authored size
 * — is `src/tests/hook/vegaSpecSizing.test.ts`, where it can be tested without
 * mocking the ESM `vega` / `vega-lite` modules.
 */
import React from 'react';
import { render } from '@testing-library/react';

jest.mock('../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ dashboardOn: false }),
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

const OUTPUT_ID = 'vega-n1';

const baseProps = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  data: { nodeId: 'n1', outputCallback: jest.fn() },
  output: { code: '', content: '' },
  nodeType: 'curio.builtin/vis-vega',
  readOnly: false,
  applyGrammar: jest.fn(),
  // Required by NodeEditorProps; none of them matter to this file, which is
  // about the output pane's geometry.
  code: true,
  grammar: false,
  widgets: false,
  defaultValue: '',
  // `outputIdOverride` is supplied only by vegaBehavior today, so this div is
  // the Vega mount and nothing else.
  outputId: OUTPUT_ID,
};

function mountDiv(): HTMLElement {
  const el = document.getElementById(OUTPUT_ID);
  if (!el) throw new Error(`no #${OUTPUT_ID} mount div rendered`);
  return el;
}

describe('the Vega output mount', () => {
  test('scrolls, so a chart taller than the pane is reachable', () => {
    render(<NodeEditor {...baseProps} />);
    expect(mountDiv().style.overflow).toBe('auto');
  });

  test('carries nowheel, so scrolling it does not zoom the canvas', () => {
    // Without this React Flow's ZoomPane swallows the wheel event and the
    // overflow above is unreachable in practice.
    render(<NodeEditor {...baseProps} />);
    expect(mountDiv()).toHaveClass('nowheel');
  });

  test('keeps nodrag, so dragging inside the chart does not move the node', () => {
    render(<NodeEditor {...baseProps} />);
    expect(mountDiv()).toHaveClass('nodrag');
  });

  test('still fills its pane', () => {
    render(<NodeEditor {...baseProps} />);
    const el = mountDiv();
    expect(el.style.width).toBe('100%');
    expect(el.style.height).toBe('100%');
  });

  test('the pane around it stays clamped, so the node box cannot spill', () => {
    // The Tab.Pane wrapping the mount must remain overflow:hidden — it is what
    // keeps a tall chart inside the node instead of painting over the canvas.
    // Reached through the mount's own parent rather than by pane id, which
    // Bootstrap derives from the tab key and is not part of this contract.
    render(<NodeEditor {...baseProps} />);
    const pane = mountDiv().parentElement as HTMLElement;
    expect(pane).not.toBeNull();
    expect(pane.style.overflow).toBe('hidden');
  });
});
