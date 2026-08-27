/**
 * How a node's source reaches WidgetsEditor, and who gets to change the tab.
 *
 * Two coupled behaviours, both previously untested:
 *
 * 1. GrammarEditor never called `sendCodeToWidgets`, unlike CodeEditor. That call
 *    is the only thing that toggles `markersDirty` outside a run, and
 *    WidgetsEditor only recomputes its marker list on that toggle — so a grammar
 *    spec containing `[!! name$WIDGET$default !!]` rendered no widgets until the
 *    node had been played once. Nothing shipped hits it (no grammar template or
 *    example uses markers) but autk-grammar and vis-vega both declare
 *    `hasWidgets: true`, so a user typing one lands straight in it.
 *
 * 2. Adding that call alone is NOT enough, and is actively worse: the widgets
 *    round-trip reaches `sendReplacedCode`, which used to call
 *    `setActiveTab("output")` unconditionally. So resolving markers on *load*
 *    yanked the user off the editor they had just opened. The load path now
 *    flags itself (`primeWidgets`) and only that path suppresses the jump.
 *
 * The flag is deliberate rather than inferring "is this a run?" from
 * `output.code === "exec"`. That inference looks equivalent and is not: play sets
 * exec and calls sendCode in the *same tick*, so the synchronous no-widgets route
 * still reads the stale prop and would never focus the output pane again. Both
 * run routes are therefore pinned below - the async one through WidgetsEditor and
 * the synchronous one a `hasWidgets: false` node takes.
 *
 * WidgetsEditor is stubbed with a stand-in that mimics the one thing that
 * matters here — on a `markersDirty` toggle it resolves markers and pushes the
 * result back through `sendReplacedCode`. The real component's marker parsing is
 * its own concern and is not what these tests are about.
 */
import React from 'react';
import { render, screen, act } from '@testing-library/react';

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

jest.mock('../../components/editing/WidgetsEditor', () => {
  const ReactLib = require('react');
  return {
    __esModule: true,
    default: ({ userCode, markersDirty, sendReplacedCode }: any) => {
      const bypass = ReactLib.useRef(false);
      ReactLib.useEffect(() => {
        // Mirrors the real component: a markersDirty toggle resolves the markers
        // and hands the substituted source back to the editor.
        if (bypass.current) {
          sendReplacedCode(String(userCode ?? '').replace(/\[!!.*?!!\]/g, 'resolved'));
        }
        bypass.current = true;
      }, [markersDirty]);
      return <div data-testid="widgets-usercode">{JSON.stringify(userCode)}</div>;
    },
  };
});

jest.mock('../../components/editing/NodeProvenance', () => ({
  __esModule: true,
  default: () => null,
}));

import NodeEditor from '../../components/editing/NodeEditor';

const MARKER = '[!! label$INPUT_TEXT$hello !!]';
const GRAMMAR_SPEC = `{\n  "title": "${MARKER}"\n}`;
const PYTHON_SOURCE = `x = "${MARKER}"\n`;

const baseProps = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  data: { nodeId: 'n1', outputCallback: jest.fn() },
  output: { code: '', content: '' },
  nodeType: 'curio.builtin/autk-grammar',
  readOnly: false,
  applyGrammar: jest.fn(),
  // A contentComponent is what makes the output pane exist at all, and therefore
  // what makes the tab jump reachable.
  contentComponent: <div />,
};

/** id suffix of the active Bootstrap tab pane, e.g. "grammar" / "code" / "output". */
function activePane(): string | null {
  const pane = document.querySelector('.tab-pane.active');
  const id = pane?.getAttribute('id') ?? '';
  const match = id.match(/tabpane-(.+)$/);
  return match ? match[1] : null;
}

const userCodeSeen = () => JSON.parse(screen.getByTestId('widgets-usercode').textContent || 'null');

describe('source reaching WidgetsEditor on load', () => {
  test('a grammar node hands its spec over, and keeps the grammar tab', () => {
    render(
      <NodeEditor
        {...(baseProps as any)}
        code={false}
        grammar={true}
        widgets={true}
        defaultValue={GRAMMAR_SPEC}
      />,
    );

    expect(userCodeSeen()).toBe(GRAMMAR_SPEC);
    // The regression the naive one-line fix introduced: resolving markers must
    // not move the user off the editor they just opened.
    expect(activePane()).toBe('grammar');
  });

  test('a code node hands its source over, and keeps the code tab', () => {
    render(
      <NodeEditor
        {...(baseProps as any)}
        nodeType={'curio.builtin/computation-analysis'}
        code={true}
        grammar={false}
        widgets={true}
        defaultValue={PYTHON_SOURCE}
      />,
    );

    expect(userCodeSeen()).toBe(PYTHON_SOURCE);
    // Previously "output": CodeEditor has always pushed to widgets on load, so
    // any python node with widgets opened on its output pane.
    expect(activePane()).toBe('code');
  });
});

describe('during a run the output tab still takes focus', () => {
  // Suppressing the tab jump on load must not suppress it on a run, and there are
  // TWO routes to it. Inferring "is this a run?" from `output.code === "exec"`
  // passes the first and fails the second: UniversalNode sets exec and calls
  // sendCode in the same tick, so the synchronous route still sees the old prop.
  // Hence the explicit load-only flag, and hence both cases below.

  test('widgets route: play focuses the output pane', () => {
    let play: ((code: string) => void) | undefined;
    const props: any = {
      ...baseProps,
      setSendCodeCallback: (cb: any) => { play = cb; },
      code: false,
      grammar: true,
      widgets: true,
      defaultValue: GRAMMAR_SPEC,
    };
    render(<NodeEditor {...props} />);
    expect(activePane()).toBe('grammar');

    act(() => { play!(GRAMMAR_SPEC); });
    expect(activePane()).toBe('output');
  });

  test('no-widgets route: play focuses the output pane synchronously', () => {
    // The data-summary shape: hasCode, no widgets tab, but it does have an
    // output pane. sendCodeToWidgets forwards straight to sendReplacedCode here,
    // inside the same tick as play, with `output` still stale.
    let play: ((code: string) => void) | undefined;
    const props: any = {
      ...baseProps,
      setSendCodeCallback: (cb: any) => { play = cb; },
      nodeType: 'curio.builtin/data-summary',
      code: true,
      grammar: false,
      widgets: false,
      defaultValue: 'return 1\n',
    };
    render(<NodeEditor {...props} />);
    expect(activePane()).toBe('code');

    act(() => { play!('return 1\n'); });
    expect(activePane()).toBe('output');
  });
});
