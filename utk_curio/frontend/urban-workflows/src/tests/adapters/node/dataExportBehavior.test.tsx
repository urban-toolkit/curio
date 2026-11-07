/**
 * Data Export's behavior: its Python code writes the file (`curio_export`), and
 * its Download button, on the Widgets tab under File name (`controlsComponent`),
 * saves the file the node's output names, read at `/output-file` by the
 * output's artifact id. A node with no current result runs first, with the
 * nodes before it, and a run that fails hands out nothing.
 */
import fs from 'fs';
import path from 'path';
import React from 'react';
import { renderHook, render, act, waitFor, fireEvent } from '@testing-library/react';
import type { NodeBehaviorHook, NodeBehaviorData, UseNodeStateReturn, NodeBehaviorResult } from '../../../registry/types';

jest.setTimeout(15000);

// What the flow tells the node: how to run up to it, whether a run goes, and
// each node's last output; settable per test, reset in afterEach.
const mockPlayNodesUpTo = jest.fn();
let mockIsRunActive = false;
let mockOutputs: any[] = [];
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({
    playNodesUpTo: mockPlayNodesUpTo,
    isRunActive: mockIsRunActive,
    serverRunActive: false,
    outputs: mockOutputs,
    nodes: [],
  }),
}));

// jsdom has no URL.createObjectURL; the export tests only need to know it was asked.
jest.mock('../../../services/packages/packagesBlobTransport', () => ({
  ...jest.requireActual('../../../services/packages/packagesBlobTransport'),
  triggerBlobDownload: jest.fn(),
}));

jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('../../../services/api', () => ({
  fetchData: jest.fn().mockResolvedValue({ data: {}, dataType: 'dataframe' }),
  fetchPreviewData: jest.fn().mockResolvedValue({ data: {}, dataType: 'dataframe' }),
  fetchRaster: jest.fn(),
}));

// The node's input edge and what feeds it; settable per test.
let mockEdges: any[] = [];
let mockNodes: Record<string, any> = {};
jest.mock('reactflow', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useEdges: () => mockEdges,
  useReactFlow: () => ({ getNode: (id: string) => mockNodes[id] }),
}));

import { useDataExportBehavior } from '../../../adapters/node/dataExportBehavior';
import { triggerBlobDownload } from '../../../services/packages/packagesBlobTransport';
import { fetchData, fetchPreviewData } from '../../../services/api';
import { runKeyOf } from '../../../utils/references/runKeys';
import { registerNodeSettingWriter } from '../../../utils/nodeSettingsWriters';

/** The parts of inputs, labelled as the zip labels them (utils/dataExportParts.cases.json). */
interface PartsCase { name: string; container?: string; inline?: boolean; envelope: any; labels: string[] | null }
const PARTS_CASES: PartsCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../../../utils/dataExportParts.cases.json'), 'utf8'),
).cases;
const partsCase = (name: string) => PARTS_CASES.find((c) => c.name.startsWith(name))!;
/** The data type an input of each container arrives with. */
const INPUT_TYPES: Record<string, string> = { tuple: 'outputs', list: 'list', dict: 'dict' };

function makeMockData(overrides: Partial<NodeBehaviorData> = {}): NodeBehaviorData {
  return {
    nodeId: 'node-1',
    nodeType: 'curio.builtin/data-export@1',
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
    input: '',
    ...overrides,
  };
}

function makeMockNodeState(overrides: Partial<UseNodeStateReturn> = {}): UseNodeStateReturn {
  return {
    output: { code: '', content: '', outputType: '' },
    setOutput: jest.fn(),
    code: '',
    setCode: jest.fn(),
    sendCode: undefined,
    templateData: {},
    setTemplateData: jest.fn(),
    newTemplateFlag: false,
    showDescriptionModal: false,
    user: undefined,
    setTemplateConfig: jest.fn(),
    promptModal: jest.fn(),
    closeModal: jest.fn(),
    promptDescription: jest.fn(),
    closeDescription: jest.fn(),
    updateTemplate: jest.fn(),
    setSendCodeCallback: jest.fn(),
    ...overrides,
  } as unknown as UseNodeStateReturn;
}

const BEHAVIOR_RESULT_KEYS: (keyof NodeBehaviorResult)[] = [
  'applyGrammar',
  'customWidgetsCallback',
  'defaultValueOverride',
  'sendCodeOverride',
  'setSendCodeCallbackOverride',
  'showLoading',
  'contentComponent',
  'controlsComponent',
  'setOutputCallbackOverride',
  'outputOverride',
  'outputIdOverride',
  'disablePlay',
  'dynamicHandles',
  'handlesOverride',
  'ownWidgets',
];

function assertValidBehaviorResult(result: NodeBehaviorResult) {
  for (const key of Object.keys(result)) {
    expect(BEHAVIOR_RESULT_KEYS).toContain(key);
  }
}

async function callBehavior(
  hook: NodeBehaviorHook,
  data?: Partial<NodeBehaviorData>,
  nodeState?: Partial<UseNodeStateReturn>,
) {
  const stableData = makeMockData(data);
  const stableNodeState = makeMockNodeState(nodeState);
  let hookResult: { current: NodeBehaviorResult };
  await act(async () => {
    const rendered = renderHook(() =>
      hook(stableData, stableNodeState),
    );
    hookResult = rendered.result;
  });
  return hookResult!;
}

describe('Behavior hooks — NodeBehaviorHook contract conformance', () => {
  describe('useDataExportBehavior', () => {
    // `/output-file`, as the backend answers it: the file an output names.
    const realFetch = (global as any).fetch;
    const mockFetch = jest.fn();
    beforeEach(() => { (global as any).fetch = mockFetch; });
    afterEach(() => {
      (global as any).fetch = realFetch;
      mockFetch.mockReset();
      mockEdges = [];
      mockNodes = {};
      mockIsRunActive = false;
      mockOutputs = [];
      mockPlayNodesUpTo.mockClear();
      (triggerBlobDownload as jest.Mock).mockClear();
      (fetchData as jest.Mock).mockReset();
      (fetchData as jest.Mock).mockResolvedValue({ data: {}, dataType: 'dataframe' });
    });

    const WIRED = [{ id: 'e1', source: 'upstream-1', target: 'node-1' }];
    const CODE = 'return curio_export(input_0, [!! file_name !!])\n';
    const FILE = new Blob(['a,b\n1,2\n'], { type: 'text/csv' });

    /** What the route answers: the file, or a refusal with its reason. */
    function serves(reply: { ok: boolean; status?: number; body?: unknown }) {
      mockFetch.mockImplementation(async () => ({
        ok: reply.ok,
        status: reply.status ?? 200,
        blob: async () => FILE,
        json: async () => reply.body ?? {},
      }));
    }
    /** The addresses the node asked for a file at. */
    const askedFor = () => mockFetch.mock.calls.map(([url]) => String(url));

    /** The node's own output: the artifact its run stored, the file's name. */
    function wroteFile(path: string, name: string) {
      mockOutputs = [{ nodeId: 'node-1', output: { path, dataType: 'str' } }];
      (fetchData as jest.Mock).mockImplementation(async (asked: string) => (
        asked === path ? { dataType: 'str', data: name } : { data: {}, dataType: 'dataframe' }
      ));
    }

    /** A Data Export node whose last run *succeeded* with the code and
     *  widgets it holds now, or with others (a stale result). */
    function exportNode(succeeded: boolean, { stale = false } = {}) {
      const data = makeMockData({ nodeType: 'curio.builtin/data-export@1', input: { path: 'in', dataType: 'dataframe' } as any });
      if (succeeded) {
        (data as any).executedCode = runKeyOf(stale ? 'return 1\n' : CODE, undefined, undefined);
      }
      const nodeState = makeMockNodeState({
        code: CODE,
        output: { code: succeeded ? 'success' : '', content: '', outputType: '' },
      } as any);
      return { data, nodeState };
    }

    function mount(data: NodeBehaviorData, nodeState: UseNodeStateReturn) {
      return renderHook(
        ({ data: d, nodeState: s }) => useDataExportBehavior(d, s),
        { initialProps: { data, nodeState } },
      );
    }

    /** The node's controls, as its Widgets tab shows them, drawn
     *  again in one place on each call. A new tree on each call made every
     *  `waitFor` poll a change of the page, which woke the wait to draw yet
     *  another, until the Jest worker ran out of memory. */
    let shown: ReturnType<typeof render> | null = null;
    afterEach(() => { shown = null; });
    function controls(result: { current: NodeBehaviorResult }) {
      const tree = <>{result.current.controlsComponent}</>;
      if (shown) shown.rerender(tree);
      else shown = render(tree);
      return shown.container;
    }
    function downloadButton(result: { current: NodeBehaviorResult }): HTMLButtonElement {
      return controls(result).querySelector('button[data-download-button]') as HTMLButtonElement;
    }

    test('adds a Download control to its Widgets tab: no Output tab, and it runs as any code node', async () => {
      const result = await callBehavior(useDataExportBehavior);
      assertValidBehaviorResult(result.current);
      expect(result.current.controlsComponent).toBeDefined();
      // A contentComponent is what makes NodeEditor show an Output tab.
      expect(result.current.contentComponent).toBeUndefined();
      // Its play runs its code: nothing replaces the code node's run.
      expect(result.current.sendCodeOverride).toBeUndefined();
      expect(result.current.setSendCodeCallbackOverride).toBeUndefined();
      const container = controls(result);
      expect(container.querySelectorAll('button')).toHaveLength(1);
      expect(container.textContent).not.toContain('output');
    });

    test('unconnected: the button is disabled and says why', async () => {
      const result = await callBehavior(useDataExportBehavior);
      const button = downloadButton(result);
      expect(button.disabled).toBe(true);
      expect(controls(result).textContent).toContain('Connect a dataset to export it');
    });

    // #513: a success output set on mount read "Done" before anything had
    // run. The node's output is its code's run's alone.
    test.each([
      ['unconnected', ''],
      ['connected', { path: 'p', dataType: 'dataframe' }],
    ])('says nothing ran until it runs (%s)', async (_label, input) => {
      const setOutput = jest.fn();
      await callBehavior(useDataExportBehavior, { input: input as any }, { setOutput });
      expect(setOutput).not.toHaveBeenCalled();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    test('with a current result, a click downloads the file the route serves, under its name, without a run', async () => {
      mockEdges = WIRED;
      wroteFile('art-1', 'trees.csv');
      serves({ ok: true });
      const { data, nodeState } = exportNode(true);
      const { result } = mount(data, nodeState);
      await waitFor(() => expect(downloadButton(result).textContent).toBe('Download trees.csv'));

      const setOutput = nodeState.setOutput as jest.Mock;
      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });

      await waitFor(() => expect(triggerBlobDownload).toHaveBeenCalledTimes(1));
      // Asked by the output's artifact id, never by a path.
      expect(askedFor()).toEqual([expect.stringMatching(/\/output-file\?fileName=art-1$/)]);
      expect(triggerBlobDownload).toHaveBeenCalledWith(FILE, 'trees.csv');
      expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
      // The download never stands in for the node's own run.
      expect(setOutput).not.toHaveBeenCalled();
      await waitFor(() => expect(controls(result).textContent).toContain('Downloaded trees.csv'));
    });

    test('a file named by default downloads under the name of what feeds the node', async () => {
      mockEdges = WIRED;
      mockNodes = {
        'upstream-1': {
          id: 'upstream-1',
          data: { nodeType: 'curio.builtin/data-loading@1', datasetSource: { title: 'boundaries.geojson' } },
        },
      };
      wroteFile('art-1', 'data_export.geojson');
      serves({ ok: true });
      const { data, nodeState } = exportNode(true);
      const { result } = mount(data, nodeState);
      await waitFor(() => expect(downloadButton(result).textContent).toBe('Download boundaries.geojson'));
      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });
      await waitFor(() => expect(triggerBlobDownload).toHaveBeenCalledWith(FILE, 'boundaries.geojson'));
    });

    test('with no result, a click runs the node and the nodes before it, then downloads the file that run wrote, once', async () => {
      mockEdges = WIRED;
      serves({ ok: true });
      const { data, nodeState } = exportNode(false);
      const { result, rerender } = mount(data, nodeState);

      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });
      expect(mockPlayNodesUpTo).toHaveBeenCalledWith('node-1');
      expect(mockFetch).not.toHaveBeenCalled();

      // The run starts, the node writes its file, the run ends.
      mockIsRunActive = true;
      await act(async () => { rerender({ data, nodeState }); });
      wroteFile('art-2', 'trees.csv');
      const ran = { ...nodeState, output: { code: 'success', content: '', outputType: '' } } as UseNodeStateReturn;
      await act(async () => { rerender({ data, nodeState: ran }); });
      expect(mockFetch).not.toHaveBeenCalled();
      mockIsRunActive = false;
      await act(async () => { rerender({ data, nodeState: ran }); });

      await waitFor(() => expect(triggerBlobDownload).toHaveBeenCalledTimes(1));
      expect(askedFor()).toEqual([expect.stringMatching(/\/output-file\?fileName=art-2$/)]);
      expect(triggerBlobDownload).toHaveBeenCalledWith(FILE, 'trees.csv');
      await act(async () => { rerender({ data, nodeState: ran }); });
      expect(triggerBlobDownload).toHaveBeenCalledTimes(1);
    });

    test('a result older than the node\'s code or widgets runs again before it downloads', async () => {
      mockEdges = WIRED;
      wroteFile('art-1', 'trees.csv');
      const { data, nodeState } = exportNode(true, { stale: true });
      const { result } = mount(data, nodeState);
      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });
      expect(mockPlayNodesUpTo).toHaveBeenCalledWith('node-1');
      expect(mockFetch).not.toHaveBeenCalled();
    });

    test('a run that fails hands out nothing, not even the file an earlier run wrote', async () => {
      mockEdges = WIRED;
      wroteFile('art-1', 'trees.csv');
      const { data, nodeState } = exportNode(true, { stale: true });
      const { result, rerender } = mount(data, nodeState);
      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });

      mockIsRunActive = true;
      await act(async () => { rerender({ data, nodeState }); });
      const failed = { ...nodeState, output: { code: 'error', content: 'Traceback', outputType: '' } } as UseNodeStateReturn;
      mockIsRunActive = false;
      await act(async () => { rerender({ data, nodeState: failed }); });

      expect(mockFetch).not.toHaveBeenCalled();
      expect(triggerBlobDownload).not.toHaveBeenCalled();
      expect(controls(result).textContent).toContain('Could not export: the node failed.');
    });

    test('a download the route refuses says why, and saves nothing', async () => {
      mockEdges = WIRED;
      wroteFile('art-1', '/etc/passwd');
      serves({
        ok: false,
        status: 403,
        body: { error: 'outside', message: 'This node\'s output names a file outside the folder of the run that made it.' },
      });
      const { data, nodeState } = exportNode(true);
      const { result } = mount(data, nodeState);
      // Found before the act: a tree drawn inside an act is committed only
      // when that act ends.
      const button = downloadButton(result);
      await act(async () => { button.click(); });
      await waitFor(() => expect(controls(result).textContent).toContain('outside the folder of the run that made it'));
      expect(triggerBlobDownload).not.toHaveBeenCalled();
    });

    // -- Part: a dropdown of the parts of an input of several ------------------

    describe('its Part dropdown', () => {
      const STARTER = 'return curio_export(input_0, [!! file_name !!], part=[!! part !!])\n';
      afterEach(() => {
        (fetchPreviewData as jest.Mock).mockReset();
        (fetchPreviewData as jest.Mock).mockResolvedValue({ data: {}, dataType: 'dataframe' });
      });

      /** The input's envelope, as `/get-preview` answers it for its artifact. */
      function holds(envelope: unknown) {
        (fetchPreviewData as jest.Mock).mockImplementation(async (asked: string) => (
          asked === 'in' ? envelope : { data: {}, dataType: 'dataframe' }
        ));
      }

      /** A wired Data Export node fed *input*, its Part widget holding *part*. */
      function partNode(input: unknown, part = '') {
        mockEdges = WIRED;
        const data = makeMockData({
          input: input as any,
          widgets: [
            { name: 'file_name', type: 'text', label: 'File name', default: '' },
            { name: 'part', type: 'text', label: 'Part', default: '', value: part },
          ],
        } as any);
        return mount(data, makeMockNodeState({ code: STARTER }));
      }

      const picker = (result: { current: NodeBehaviorResult }) =>
        controls(result).querySelector('select[aria-label="Part"]') as HTMLSelectElement | null;
      const optionsOf = (select: HTMLSelectElement) => Array.from(select.options);

      test('draws its own Part, so the node shows no text box for it', async () => {
        const result = await callBehavior(useDataExportBehavior);
        expect(result.current.ownWidgets).toEqual(['part']);
      });

      test('shows no Part for one table, geo table or raster, unconnected, or before a result', async () => {
        for (const dataType of ['dataframe', 'geodataframe', 'raster']) {
          const { result, unmount } = partNode({ path: 'in', dataType });
          expect(picker(result)).toBeNull();
          unmount();
          shown = null;
        }
        expect(fetchPreviewData).not.toHaveBeenCalled();

        // Wired, but the node before it has no result yet.
        const before = partNode('');
        expect(picker(before.result)).toBeNull();
        before.unmount();
        shown = null;

        // A list that holds no table or raster is written as JSON: no parts.
        holds(partsCase('a list of numbers').envelope);
        const json = partNode({ path: 'in', dataType: 'list' });
        await waitFor(() => expect(fetchPreviewData).toHaveBeenCalledWith('in'));
        await act(async () => {});
        expect(picker(json.result)).toBeNull();
        json.unmount();
        shown = null;

        // Unconnected: nothing feeds it, whatever its data still holds.
        holds(partsCase('the Chicago Loop Layers').envelope);
        const data = makeMockData({ input: { path: 'in', dataType: 'outputs' } as any });
        mockEdges = [];
        const { result } = mount(data, makeMockNodeState({ code: STARTER }));
        await act(async () => {});
        expect(picker(result)).toBeNull();
      });

      test.each(
        PARTS_CASES.filter((c) => c.labels !== null).map((c) => [c.name, c] as const),
      )('offers All parts, then each part by the label the zip names its file after: %s', async (_name, c) => {
        holds(c.envelope);
        // An Autark node's layers arrive inline; a node's output, by its artifact.
        const input = c.inline ? c.envelope : { path: 'in', dataType: INPUT_TYPES[c.container!] };
        const { result } = partNode(input);
        await waitFor(() => expect(picker(result)).not.toBeNull());
        const select = picker(result)!;
        expect(optionsOf(select).map((o) => o.getAttribute('data-label') ?? o.textContent)).toEqual([
          'All parts', ...c.labels!,
        ]);
        expect(optionsOf(select)[0].value).toBe('');
        expect(select.value).toBe('');
      });

      test('All parts writes the empty value, and a pick its label, or its position when labels repeat', async () => {
        const writes = jest.fn();
        const off = registerNodeSettingWriter('node-1', 'widgets', writes);
        try {
          holds(partsCase('the Chicago Loop Layers').envelope);
          const chicago = partNode({ path: 'in', dataType: 'outputs' });
          await waitFor(() => expect(picker(chicago.result)).not.toBeNull());
          fireEvent.change(picker(chicago.result)!, { target: { value: 'Trees (OpenStreetMap)' } });
          expect(writes).toHaveBeenLastCalledWith({ part: 'Trees (OpenStreetMap)' });
          expect(picker(chicago.result)!.value).toBe('Trees (OpenStreetMap)');
          fireEvent.change(picker(chicago.result)!, { target: { value: '' } });
          expect(writes).toHaveBeenLastCalledWith({ part: '' });
          chicago.unmount();
          shown = null;

          holds(partsCase('two tables that carry one label').envelope);
          const twice = partNode({ path: 'in', dataType: 'outputs' });
          await waitFor(() => expect(picker(twice.result)).not.toBeNull());
          expect(optionsOf(picker(twice.result)!).map((o) => o.value)).toEqual(['', '0', '1']);
          fireEvent.change(picker(twice.result)!, { target: { value: '1' } });
          expect(writes).toHaveBeenLastCalledWith({ part: '1' });
        } finally {
          off();
        }
      });

      test('a saved part the input no longer holds stays selected, marked as not in the input', async () => {
        holds(partsCase('the Chicago Loop Layers').envelope);
        const { result } = partNode({ path: 'in', dataType: 'outputs' }, 'Roads');
        await waitFor(() => expect(picker(result)).not.toBeNull());
        const select = picker(result)!;
        expect(select.value).toBe('Roads');
        expect(select.getAttribute('data-stale')).toBe('true');
        expect(optionsOf(select).find((o) => o.selected)!.textContent).toBe('Roads (not in the input)');
        // A part the input holds, by its position, is no stale value.
        const { result: byPosition } = partNode({ path: 'in', dataType: 'outputs' }, '2');
        await waitFor(() => expect(picker(byPosition)?.value).toBe('Trees (OpenStreetMap)'));
      });

      test('a long label is cut in the list, and the whole of the chosen one shows on hover', async () => {
        const census = "Census tracts with CDC/ATSDR's Social Vulnerability Index 2020";
        holds(partsCase('the Chicago Loop Layers').envelope);
        const { result } = partNode({ path: 'in', dataType: 'outputs' }, census);
        await waitFor(() => expect(picker(result)).not.toBeNull());
        const select = picker(result)!;
        const option = optionsOf(select).find((o) => o.value === census)!;
        expect(option.textContent!.length).toBeLessThan(census.length);
        expect(option.textContent!.endsWith('…')).toBe(true);
        expect(select.getAttribute('data-tooltip')).toBe(census);
        expect(select.getAttribute('title')).toBeNull();
      });
    });


  });

});
