/**
 * Autark nodes refuse to run without WebGPU, rather than crashing (#201).
 *
 * Nothing in the app asked whether the browser could do this. The library
 * swallows its own init failure — `Renderer.init()` only `console.error`s
 * "WebGPU is not available" and leaves `_device` undefined — so `AutkMap.init()`
 * carried on until the layer loader reached
 * `this._renderer.device.createShaderModule` and threw a TypeError with a stack
 * that says nothing about WebGPU. With no error boundary anywhere, that throw
 * took the whole React root down.
 *
 * jsdom has no `navigator.gpu`, so "unsupported" is the default here and only
 * the supported case needs to install one.
 */
import React from 'react';
import { render, act, waitFor, fireEvent } from '@testing-library/react';

const mockShowToast = jest.fn();
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn() }));
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock('../../../adapters/autkGrammarAdapter', () => ({
  autkGrammarAdapter: { getDefaultSpec: () => '{"map":{}}' },
}));

const mockGrammarRun = jest.fn().mockResolvedValue(undefined);
const mockAutkGrammar = jest.fn().mockImplementation(() => ({
  run: mockGrammarRun,
  data: {},
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({ AutkGrammar: mockAutkGrammar }),
  { virtual: true },
);

const mockComputeGpgpu = jest.fn().mockImplementation(() => ({}));
jest.mock(
  '@urban-toolkit/autk-compute',
  () => ({ ComputeGpgpu: mockComputeGpgpu }),
  { virtual: true },
);

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import {
  __resetWebGpuSupportCache,
  __setWebGpuAdapterRetryBudget,
  WEBGPU_ADAPTER_RETRY_BUDGET_MS,
} from '../../../utils/webgpuSupport';

const MAP_SPEC = JSON.stringify({ map: { layerRefs: [] } });
const COMPUTE_SPEC = JSON.stringify({
  compute: [{ dataRef: 'upstream', wglsFunction: 'fn main() {}' }],
});

interface Harness {
  apply: (spec: string) => Promise<void>;
  outputs: Array<{ code: string; content: string }>;
  content: () => React.ReactNode;
}

function renderBehavior(): Harness {
  const outputs: Array<{ code: string; content: string }> = [];
  const harness: Partial<Harness> = { outputs };
  let latestContent: React.ReactNode = null;

  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: 'autk-1', input: '', defaultCode: MAP_SPEC } as any,
      {
        output: { code: '', content: '' },
        setOutput: (o: { code: string; content: string }) => outputs.push(o),
        setCode: jest.fn(),
        templateData: {},
      } as any,
    );
    harness.apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    latestContent = behavior.contentComponent;
    return <>{behavior.contentComponent}</>;
  };

  render(<Probe />);
  harness.content = () => latestContent;
  return harness as Harness;
}

/** Installs a `navigator.gpu` whose `requestAdapter` answers with *adapter*. */
function withGpu(adapter: unknown, { throws = false } = {}) {
  Object.defineProperty(navigator, 'gpu', {
    configurable: true,
    value: {
      requestAdapter: throws
        ? jest.fn().mockRejectedValue(new Error('pref disabled'))
        : jest.fn().mockResolvedValue(adapter),
      // autk-map calls this before requestAdapter; the probe checks for it.
      getPreferredCanvasFormat: () => 'bgra8unorm',
    },
  });
}

function withoutGpu() {
  Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
}

beforeEach(() => {
  jest.clearAllMocks();
  __resetWebGpuSupportCache();
  // The subject here is the fallback panel and the node's output, not the
  // retry policy - which has its own suite (webgpuSupport.test.ts) and its own
  // fake-timer harness. Without this every "no adapter" case below would sit
  // through the real budget on real timers (#272).
  __setWebGpuAdapterRetryBudget(0);
  withoutGpu();
});

afterEach(() => {
  __setWebGpuAdapterRetryBudget(WEBGPU_ADAPTER_RETRY_BUDGET_MS);
});

describe('an Autark node on a browser without WebGPU', () => {
  test('refuses to run, and never constructs the grammar', async () => {
    const h = renderBehavior();

    // Resolves rather than throwing: an escaped rejection is what the
    // dev-server overlay listens for.
    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockAutkGrammar).not.toHaveBeenCalled();
    const errors = h.outputs.filter((o) => o.code === 'error');
    expect(errors).toHaveLength(1);
    expect(errors[0].content).toMatch(/WebGPU/i);
  });

  test('names the remedy, not just the problem', async () => {
    const h = renderBehavior();
    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    const message = h.outputs.find((o) => o.code === 'error')!.content;
    // A user on Firefox has an action available; the message has to name it.
    expect(message).toMatch(/Chrome|Edge/);
    expect(message).toMatch(/dom\.webgpu\.enabled|about:config/);
  });

  test('says so in the node, as an alert', async () => {
    const h = renderBehavior();
    const { rerender } = render(<>{h.content()}</>);
    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    await waitFor(() => {
      rerender(<>{h.content()}</>);
      const alert = document.body.querySelector('[role="alert"]');
      expect(alert).not.toBeNull();
      expect(alert!.textContent).toMatch(/WebGPU is not available/i);
    });
  });

  test('a compute-only spec emits no output at all, rather than uncomputed data', async () => {
    const h = renderBehavior();

    await act(async () => {
      await h.apply(COMPUTE_SPEC);
    });

    expect(mockComputeGpgpu).not.toHaveBeenCalled();
    // The point of the issue's silent half: the node must not report success
    // while handing downstream nodes its untouched input.
    expect(h.outputs.filter((o) => o.code === 'success')).toHaveLength(0);
    expect(h.outputs.some((o) => o.code === 'error')).toBe(true);
  });

  test('toasts once, so the failure is visible without opening the node', async () => {
    const h = renderBehavior();
    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockShowToast).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringMatching(/WebGPU/i),
      'error',
    );
  });
});

describe('an Autark node where the API exists but no adapter does', () => {
  test('still refuses — presence of navigator.gpu is not the test', async () => {
    // Chrome exposes navigator.gpu on blocklisted drivers and in headless runs,
    // then resolves requestAdapter() to null. Checking only for the object
    // would sail straight into the same TypeError.
    withGpu(null);
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockAutkGrammar).not.toHaveBeenCalled();
    expect(h.outputs.some((o) => o.code === 'error')).toBe(true);
  });

  test('a throwing requestAdapter is contained too', async () => {
    // Firefox throws here rather than resolving null when the pref is off.
    withGpu(null, { throws: true });
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockAutkGrammar).not.toHaveBeenCalled();
    expect(h.outputs.some((o) => o.code === 'error')).toBe(true);
  });
});

describe('an Autark node on a browser that does have WebGPU', () => {
  test('runs the grammar, so Chrome is not regressed', async () => {
    withGpu({ name: 'fake-adapter' });
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockAutkGrammar).toHaveBeenCalled();
    expect(mockGrammarRun).toHaveBeenCalled();
    expect(h.outputs.filter((o) => o.code === 'error')).toHaveLength(0);
    expect(document.body.querySelector('[role="alert"]')).toBeNull();
  });
});

describe('Firefox: the adapter arrives on the second ask (#272)', () => {
  test('null on the first requestAdapter, an adapter on the retry, and the grammar runs', async () => {
    // The one case here that IS about the retry, so it needs a budget to retry
    // within. One backoff step (150 ms) on real timers is the whole cost.
    __setWebGpuAdapterRetryBudget(500);
    Object.defineProperty(navigator, 'gpu', {
      configurable: true,
      value: {
        requestAdapter: jest.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ name: 'late' }),
        getPreferredCanvasFormat: () => 'bgra8unorm',
      },
    });
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockAutkGrammar).toHaveBeenCalled();
    expect(h.outputs.filter((o) => o.code === 'error')).toHaveLength(0);
  });
});

describe('"Check again" on the fallback panel (#272)', () => {
  const checkAgainButton = () =>
    document.body.querySelector('button[aria-label="Check WebGPU again"]') as HTMLButtonElement | null;

  test('re-probes and, once WebGPU answers, runs the spec without another play', async () => {
    const h = renderBehavior();
    await act(async () => {
      await h.apply(MAP_SPEC);
    });
    await waitFor(() => expect(checkAgainButton()).not.toBeNull());
    expect(mockAutkGrammar).not.toHaveBeenCalled();

    // The pref was flipped / the GPU process came up.
    withGpu({ name: 'fake-adapter' });
    await act(async () => {
      fireEvent.click(checkAgainButton()!);
    });

    await waitFor(() => {
      expect(mockAutkGrammar).toHaveBeenCalled();
      expect(document.body.querySelector('[role="alert"]')).toBeNull();
    });
    expect(h.outputs.at(-1)).toEqual(expect.objectContaining({ code: 'success' }));
  });

  test('while WebGPU is still missing, the panel stays and the toast fires again', async () => {
    const h = renderBehavior();
    await act(async () => {
      await h.apply(MAP_SPEC);
    });
    await waitFor(() => expect(checkAgainButton()).not.toBeNull());
    expect(mockShowToast).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(checkAgainButton()!);
    });

    await waitFor(() => expect(mockShowToast).toHaveBeenCalledTimes(2));
    expect(document.body.querySelector('[role="alert"]')).not.toBeNull();
    expect(mockAutkGrammar).not.toHaveBeenCalled();
  });
});

describe('the run always ends (#271)', () => {
  const terminal = (h: Harness) => h.outputs.filter((o) => o.code === 'success' || o.code === 'error');

  test('a WebGPU refusal is exactly one terminal output, so the runner is released once', async () => {
    const h = renderBehavior();
    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0].code).toBe('error');
  });

  test('a grammar whose run() rejects still ends with one error output carrying the message', async () => {
    withGpu({ name: 'fake-adapter' });
    mockGrammarRun.mockRejectedValueOnce(new Error('createShaderModule of undefined'));
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0]).toEqual({
      code: 'error',
      content: expect.stringContaining('createShaderModule'),
    });
    // exec came first, so the node visibly went running -> error, not nothing.
    expect(h.outputs.some((o) => o.code === 'exec')).toBe(true);
  });

  test('a navigator.gpu getter that throws is an error output, not an escaped rejection', async () => {
    Object.defineProperty(navigator, 'gpu', {
      configurable: true,
      get() {
        throw new Error('gpu getter exploded');
      },
    });
    const h = renderBehavior();

    let escaped: unknown = null;
    await act(async () => {
      try {
        await h.apply(MAP_SPEC);
      } catch (err) {
        escaped = err;
      }
    });
    expect(escaped).toBeNull();

    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0].code).toBe('error');
  });
});

describe('the duckdb spatial extension (#318)', () => {
  const terminal = (h: Harness) => h.outputs.filter((o) => o.code === 'success' || o.code === 'error');
  const EXTENSION_ERROR = new Error(
    "Failed to execute 'send' on 'XMLHttpRequest': Failed to load "
    + "'https://extensions.duckdb.org/v1.5.1/wasm_eh/spatial.duckdb_extension.wasm'.",
  );

  test('a failed extension fetch is retried, and the node ends green', async () => {
    // autk-db downloads the spatial extension into every fresh in-browser
    // DuckDB, so one network flake failed a map node that had nothing to do
    // with the network.
    withGpu({ name: 'fake-adapter' });
    mockGrammarRun.mockRejectedValueOnce(EXTENSION_ERROR);
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(mockGrammarRun).toHaveBeenCalledTimes(2);
    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0].code).toBe('success');
  });

  test('an extension fetch that keeps failing reports it, once', async () => {
    withGpu({ name: 'fake-adapter' });
    mockGrammarRun.mockRejectedValue(EXTENSION_ERROR);
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0]).toEqual({
      code: 'error',
      content: expect.stringContaining('extensions.duckdb.org'),
    });
  });

  test('an error with no message still says something', async () => {
    withGpu({ name: 'fake-adapter' });
    mockGrammarRun.mockRejectedValueOnce(new TypeError(''));
    const h = renderBehavior();

    await act(async () => {
      await h.apply(MAP_SPEC);
    });

    expect(terminal(h)).toHaveLength(1);
    expect(terminal(h)[0].code).toBe('error');
    expect(terminal(h)[0].content.trim()).not.toBe('');
  });
});
