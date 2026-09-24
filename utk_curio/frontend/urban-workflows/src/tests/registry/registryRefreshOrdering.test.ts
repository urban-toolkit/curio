/**
 * A registry refresh that started earlier must not overwrite one that started later.
 *
 * `loadInstalledPackages` fetches the installed list, waits for behavior
 * scripts, and then replaces every package node in the registry. Nothing
 * checked whether a newer refresh had started while it was waiting, so the
 * refresh that FINISHED last won, not the one that STARTED last.
 *
 * That is reachable on an ordinary page load. Several surfaces call
 * `refreshPackageRegistry` on the same tick (`index.tsx`, `UserProvider`,
 * `ProjectLoader`, `ToolsMenu`), each taking a snapshot of what is installed.
 * Import a package before those settle and the import's own refresh can land
 * first, only for a boot refresh holding the older snapshot to land after it
 * and remove the package from the palette. Nothing refreshes again, so it stays
 * gone until the page is reloaded, while the server has it installed the whole
 * time. `test_package_metadata_survives_export_and_reimport` failed this way:
 * the palette count stayed at 0 for 30 seconds straight.
 *
 * The project lockfile store already guards its own version of this race
 * (`applyProjectLockfile` and its revision counter). This is the registry's.
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

// Side-effect imports first, in the order packagesClient.test.ts uses: the
// behavior and icon registries must be populated before packagesClient pulls in
// the adapter index, whose lazy getters throw on an unregistered key.
import '../../registry/builtinBehaviors';
import '../../registry/iconRegistry';
import { loadInstalledPackages } from '../../registry/packagesClient';
import { clearPackageNodes, getAllNodeTypes } from '../../registry/nodeRegistry';

const ACME = {
  packageId: 'acme.widgets',
  major: 1,
  version: '1.0.0',
  name: 'Acme Widgets',
  publisher: 'Acme',
  description: '',
  license: 'MIT',
  permissions: [],
  lineage: null,
  dirName: 'acme.widgets@1',
  templates: [
    {
      id: 'acme.widgets/widget@1',
      templateId: 'widget',
      label: 'Widget',
      category: 'data',
      engine: 'python' as const,
      description: '',
      icon: null,
      iconRef: 'fa-solid:upload',
      behavior: 'code',
      paletteOrder: 0,
      editor: 'code' as const,
      hasCode: true,
      hasWidgets: false,
      hasGrammar: false,
      grammarId: null,
      badge: null,
      inputPorts: [],
      outputPorts: [{ types: ['DATAFRAME'], cardinality: '[1,n]' }],
      source: null,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    },
  ],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function acmeIsRegistered(): boolean {
  return getAllNodeTypes().some((d) => d.package?.packageId === 'acme.widgets');
}

describe('overlapping registry refreshes', () => {
  beforeEach(() => {
    clearPackageNodes();
    mockListInstalled.mockReset();
  });

  it('keeps the newer snapshot when the older refresh finishes last', async () => {
    // The boot refresh, asked before the import: acme is not installed yet.
    const older = deferred<{ packages: unknown[] }>();
    // The import's refresh, asked after it: acme is installed now.
    const newer = deferred<{ packages: unknown[] }>();
    mockListInstalled
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);

    const boot = loadInstalledPackages();
    const afterImport = loadInstalledPackages();

    newer.resolve({ packages: [ACME] });
    await afterImport;
    expect(acmeIsRegistered()).toBe(true);

    // The older answer arrives last. It must not take the package back out.
    older.resolve({ packages: [] });
    await boot;

    expect(acmeIsRegistered()).toBe(true);
  });

  it('still applies refreshes that finish in the order they started', async () => {
    // The guard must not swallow ordinary sequential updates: an install that
    // lands after an earlier refresh has fully finished is simply newer.
    const first = deferred<{ packages: unknown[] }>();
    const second = deferred<{ packages: unknown[] }>();
    mockListInstalled
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const a = loadInstalledPackages();
    const b = loadInstalledPackages();

    first.resolve({ packages: [] });
    await a;
    second.resolve({ packages: [ACME] });
    await b;

    expect(acmeIsRegistered()).toBe(true);
  });

  it('lets an uninstall through when it is the newer refresh', async () => {
    // Ordering, not stickiness: a package must still be able to LEAVE the
    // registry when the newest snapshot says it is gone.
    const withAcme = deferred<{ packages: unknown[] }>();
    const withoutAcme = deferred<{ packages: unknown[] }>();
    mockListInstalled
      .mockReturnValueOnce(withAcme.promise)
      .mockReturnValueOnce(withoutAcme.promise);

    const beforeUninstall = loadInstalledPackages();
    const afterUninstall = loadInstalledPackages();

    withoutAcme.resolve({ packages: [] });
    await afterUninstall;
    withAcme.resolve({ packages: [ACME] });
    await beforeUninstall;

    expect(acmeIsRegistered()).toBe(false);
  });

  it('still applies an older answer when the newer refresh fails', async () => {
    // Why the rule is "never apply an answer older than one already applied"
    // rather than "only the newest call may apply". A newer call that fails
    // applies nothing, so it must not also discard an older call's good answer,
    // or a single network blip would leave the registry never updating at all.
    const older = deferred<{ packages: unknown[] }>();
    let failNewer!: (err: unknown) => void;
    const newer = new Promise<{ packages: unknown[] }>((_resolve, reject) => {
      failNewer = reject;
    });
    mockListInstalled
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer);

    const first = loadInstalledPackages();
    const second = loadInstalledPackages();

    failNewer(Object.assign(new Error('network blip'), { status: 503 }));
    await second;
    older.resolve({ packages: [ACME] });
    await first;

    expect(acmeIsRegistered()).toBe(true);
  });
});
