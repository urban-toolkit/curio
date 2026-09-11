/**
 * A package's behavior bundle is fetched once, even under concurrent refreshes.
 *
 * The regression: `loadPackageBehaviorScripts` read its de-dupe marker — a
 * `script[data-curio-package=...]` already in the DOM — at the top of the loop,
 * then awaited `fetch` and `res.text()` before writing that marker. Any caller
 * entering the window in between passed the guard, and nothing single-flights
 * `refreshPackageRegistry`, which several surfaces call on the same tick. The
 * bundle was then fetched and evaluated repeatedly on one page load, each pass
 * re-running its top-level `registerBehavior` side-effects. The stress run saw
 * `Behavior "cv-gallery" already registered; overwriting.` and three siblings,
 * eleven times each in a single chapter.
 */

// vega ships ESM that Jest's default transform skips; this suite never reaches
// the Vega compile path (same stubbing as packagesClient.test.ts).
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

jest.mock('../../utils/authApi', () => ({
  getToken: () => 'test-token',
}));

const mockListInstalled = jest.fn();
jest.mock('../../api/packagesApi', () => ({
  packagesApi: { listInstalled: (...a: unknown[]) => mockListInstalled(...a) },
}));

// Side-effect imports first, the same order packagesClient.test.ts uses: the
// behaviour and icon registries must be populated before packagesClient pulls
// in the adapter index, whose lazy getters throw on an unregistered key.
import '../../registry/builtinBehaviors';
import '../../registry/iconRegistry';
import { loadInstalledPackages } from '../../registry/packagesClient';
import { clearPackageNodes } from '../../registry/nodeRegistry';

const PACK = {
  packageId: 'acme.widgets',
  major: 1,
  version: '1.0.0',
  name: 'Acme Widgets',
  publisher: 'Acme',
  description: '',
  dirName: 'acme.widgets@1',
  behaviorScript: 'behavior.js',
  templates: [],
};

describe('behavior bundle loading', () => {
  let fetchCalls: number;

  beforeEach(() => {
    clearPackageNodes();
    document.head.querySelectorAll('script[data-curio-package]').forEach((s) => s.remove());
    fetchCalls = 0;
    mockListInstalled.mockResolvedValue({ packages: [PACK] });
    // Resolve on a later microtask so two concurrent callers genuinely overlap
    // — the exact window the old marker check could not close.
    (global as unknown as { fetch: unknown }).fetch = jest.fn(async () => {
      fetchCalls += 1;
      await Promise.resolve();
      return { ok: true, status: 200, text: async () => '/* bundle */' };
    });
  });

  it('fetches the bundle once when two refreshes overlap', async () => {
    await Promise.all([loadInstalledPackages(), loadInstalledPackages()]);
    expect(fetchCalls).toBe(1);
    expect(
      document.head.querySelectorAll('script[data-curio-package="acme.widgets@1"]'),
    ).toHaveLength(1);
  });

  it('does not refetch on a later refresh, once the marker is in the DOM', async () => {
    await loadInstalledPackages();
    await loadInstalledPackages();
    expect(fetchCalls).toBe(1);
  });

  it('releases the claim after a failed fetch, so a retry can load it', async () => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest
      .fn()
      .mockImplementationOnce(async () => {
        fetchCalls += 1;
        return { ok: false, status: 500, text: async () => '' };
      })
      .mockImplementationOnce(async () => {
        fetchCalls += 1;
        return { ok: true, status: 200, text: async () => '/* bundle */' };
      });

    await loadInstalledPackages();
    await loadInstalledPackages();
    expect(fetchCalls).toBe(2);
    expect(
      document.head.querySelectorAll('script[data-curio-package="acme.widgets@1"]'),
    ).toHaveLength(1);
  });
});
