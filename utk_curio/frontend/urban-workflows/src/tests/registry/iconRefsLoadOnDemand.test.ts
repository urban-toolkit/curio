/**
 * A package's `iconRef` names any Font Awesome solid or brands icon, with no
 * edit to Curio. An icon Curio does not bundle is loaded before the package's
 * palette tiles are built, so a tile never draws the cube first, and a name
 * Font Awesome does not have draws the cube.
 */

// vega and vega-lite ship ESM that Jest's default transform skips; this suite
// never reaches the Vega compile path (same stubbing as packagesClient.test.ts).
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

jest.mock('../../utils/authApi', () => ({
  getToken: () => 'test-token',
}));

const mockListInstalled = jest.fn();
jest.mock('../../services/packages/packagesApi', () => ({
  packagesApi: { listInstalled: (...a: unknown[]) => mockListInstalled(...a) },
}));

import { faCube, faTree } from '@fortawesome/free-solid-svg-icons';
import { faGithub } from '@fortawesome/free-brands-svg-icons';
import '../../registry/builtinBehaviors';
import { resolveIconRef } from '../../registry/iconRegistry';
import { loadInstalledPackages } from '../../registry/packagesClient';
import { clearPackageNodes, getAllNodeTypes, subscribeToRegistry } from '../../registry/nodeRegistry';

/** A template of the user package `acme.grove@1` that names `iconRef`. */
function template(templateId: string, iconRef: string) {
  return {
    id: `acme.grove/${templateId}@1`,
    templateId,
    label: templateId,
    category: 'computation',
    engine: 'python' as const,
    description: '',
    icon: null,
    iconRef,
    behavior: null,
    paletteOrder: null,
    editor: 'code' as const,
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    grammarId: null,
    badge: null,
    inputPorts: [],
    outputPorts: [],
    source: null,
    bidirectional: false,
    containerStyle: null,
    hasProvenance: null,
  };
}

function grove(...templates: ReturnType<typeof template>[]) {
  return {
    packageId: 'acme.grove',
    major: 1,
    version: '1.0.0',
    name: 'Grove',
    publisher: 'Acme',
    description: '',
    license: 'MIT',
    permissions: [],
    lineage: null,
    templates,
  };
}

const iconOf = (id: string) => getAllNodeTypes().find((d) => d.id === id)?.icon;

beforeEach(() => {
  clearPackageNodes();
  mockListInstalled.mockReset();
});

describe('an icon Curio does not bundle', () => {
  it('is drawn on the tile of a package that names it, from the first time the tile is built', async () => {
    // Neither is bundled: until a package names them, they resolve to the cube.
    expect(resolveIconRef('fa-solid:tree')).toBe(faCube);
    expect(resolveIconRef('fa-brands:github')).toBe(faCube);

    mockListInstalled.mockResolvedValue({
      packages: [grove(template('tree', 'fa-solid:tree'), template('repo', 'fa-brands:github'))],
    });
    // The icon each tile has every time the registry tells the palette it changed.
    const drawn: string[] = [];
    const stop = subscribeToRegistry(() => {
      for (const id of ['acme.grove/tree@1', 'acme.grove/repo@1']) {
        const icon = iconOf(id);
        if (icon) drawn.push(`${id} ${icon.prefix}:${icon.iconName}`);
      }
    });
    try {
      await loadInstalledPackages();
    } finally {
      stop();
    }

    expect(iconOf('acme.grove/tree@1')).toEqual(faTree);
    expect(iconOf('acme.grove/repo@1')).toEqual(faGithub);
    expect(resolveIconRef('fa-solid:tree')).toEqual(faTree);
    expect(resolveIconRef('fa-brands:github')).toEqual(faGithub);
    expect(drawn).toEqual(
      expect.arrayContaining(['acme.grove/tree@1 fas:tree', 'acme.grove/repo@1 fab:github']),
    );
    expect(drawn.filter((line) => line.endsWith(':cube'))).toEqual([]);
  });
});

describe('a name Font Awesome does not have', () => {
  it('draws the cube, and its warning does not send the author to edit Curio', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      mockListInstalled.mockResolvedValue({
        packages: [
          grove(template('mystery', 'fa-solid:no-such-icon'), template('regular', 'fa-regular:tree')),
        ],
      });
      await loadInstalledPackages();

      expect(iconOf('acme.grove/mystery@1')).toBe(faCube);
      expect(iconOf('acme.grove/regular@1')).toBe(faCube);
      const messages = warn.mock.calls.map((args) => args.map(String).join(' '));
      for (const ref of ['fa-solid:no-such-icon', 'fa-regular:tree']) {
        expect(messages.filter((message) => message.includes(ref))).not.toEqual([]);
      }
      expect(messages.filter((message) => /iconRegistry\.ts|registerIcon/.test(message))).toEqual([]);
    } finally {
      warn.mockRestore();
    }
  });
});
