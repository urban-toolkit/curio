/**
 * Regression guard for `registerPackageTemplates` (the conversion path from manifest
 * payload → `NodeDescriptor`). The 9-commit warehouse refactor moved every
 * built-in node through this function; without this test, descriptor capabilities
 * that the old `descriptors.ts` carried can be silently dropped from the
 * manifest schema and not caught until a user hits the missing behaviour.
 *
 * The fixture is a hand-written subset of `packages/curio.builtin@1/manifest.json`
 * — small enough to read in one screen, large enough to exercise:
 *   - bidirectional handles (vis-vega)
 *   - container overrides (merge-flow)
 *   - editor === 'none' → adapter.editor must be null
 *   - 'N' icon for [1,n] cardinality (data-loading output)
 *   - badge passthrough (vega), lifecycle/icon registry lookups
 */

import {
  faChartLine,
  faCodeMerge,
  faUpload,
} from '@fortawesome/free-solid-svg-icons';

// vega and vega-lite ship ESM that Jest's default transform skips. Stubbing
// them here is safe: this suite only exercises manifest → descriptor wiring,
// never the Vega-Lite compile path that vegaLiteAdapter pulls in.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import '../../registry/builtinLifecycles'; // side-effect: registers the 11 built-in lifecycles
import '../../registry/iconRegistry'; // side-effect: registers FA icons used by the fixture
import { registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes } from '../../registry/nodeRegistry';

const FIXTURE_PACK = {
  packageId: 'curio.builtin',
  major: 1,
  version: '1.0.0',
  name: 'Curio Built-in Nodes',
  publisher: 'Curio',
  description: '',
  license: 'MIT',
  permissions: [],
  lineage: null,
  templates: [
    {
      id: 'curio.builtin/data-loading@1',
      templateId: 'data-loading',
      label: 'Data Loading',
      category: 'data',
      engine: 'python' as const,
      description: '',
      icon: null,
      iconRef: 'fa-solid:upload',
      lifecycle: 'code',
      paletteOrder: 0,
      editor: 'code' as const,
      hasCode: true,
      hasWidgets: true,
      hasGrammar: false,
      grammarId: null,
      badge: null,
      inputPorts: [],
      outputPorts: [{ types: ['DATAFRAME', 'GEODATAFRAME', 'RASTER'], cardinality: '[1,n]' }],
      source: null,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
      tutorialId: 'step-loading',
    },
    {
      id: 'curio.builtin/vis-vega@1',
      templateId: 'vis-vega',
      label: 'Vega-Lite',
      category: 'vis_grammar',
      engine: 'python' as const,
      description: '',
      icon: null,
      iconRef: 'fa-solid:chart-line',
      lifecycle: 'vega',
      paletteOrder: 7,
      editor: 'grammar' as const,
      hasCode: false,
      hasWidgets: true,
      hasGrammar: true,
      grammarId: 'vega-lite',
      badge: 'VEGA',
      inputPorts: [{ types: ['DATAFRAME'], cardinality: '1' }],
      outputPorts: [{ types: ['DATAFRAME'], cardinality: '1' }],
      source: null,
      bidirectional: true,
      containerStyle: null,
      hasProvenance: true,
      tutorialId: null,
    },
    {
      id: 'curio.builtin/merge-flow@1',
      templateId: 'merge-flow',
      label: 'Merge Flow',
      category: 'flow',
      engine: 'python' as const,
      description: '',
      icon: null,
      iconRef: 'fa-solid:code-merge',
      lifecycle: 'merge-flow',
      paletteOrder: 9,
      editor: 'none' as const,
      hasCode: false,
      hasWidgets: false,
      hasGrammar: false,
      grammarId: null,
      badge: null,
      inputPorts: [{ types: ['DATAFRAME'], cardinality: '[1,n]' }],
      outputPorts: [{ types: ['DATAFRAME'], cardinality: '1' }],
      source: null,
      bidirectional: false,
      containerStyle: { nodeWidth: 50, nodeHeight: 180, noContent: true },
      hasProvenance: null,
      tutorialId: 'step-merge',
    },
  ],
};

describe('registerPackageTemplates → NodeDescriptor', () => {
  beforeEach(() => clearPackageNodes());

  test('data-loading: code editor, upload icon, N output cardinality, no badge for built-in', () => {
    const [dl] = registerPackageTemplates([FIXTURE_PACK]);
    expect(dl.id).toBe('curio.builtin/data-loading@1');
    expect(dl.icon).toBe(faUpload);
    expect(dl.badge).toBeUndefined();
    expect(dl.adapter.outputIconType).toBe('N');
    expect(dl.adapter.editor).not.toBeNull();
    expect(dl.tutorialId).toBe('step-loading');
  });

  test('vis-vega: bidirectional handle, badge="VEGA", grammarId="vega-lite", hasProvenance=true', () => {
    const [, vega] = registerPackageTemplates([FIXTURE_PACK]);
    expect(vega.id).toBe('curio.builtin/vis-vega@1');
    expect(vega.icon).toBe(faChartLine);
    expect(vega.badge).toBe('VEGA');
    expect(vega.grammarId).toBe('vega-lite');
    expect(vega.hasProvenance).toBe(true);
    // Bidirectional adds a third handle on top of the standard in/out pair.
    expect(vega.adapter.handles).toHaveLength(3);
  });

  test('merge-flow: editor=null (none), 50x180 container, custom icon', () => {
    const [, , merge] = registerPackageTemplates([FIXTURE_PACK]);
    expect(merge.id).toBe('curio.builtin/merge-flow@1');
    expect(merge.icon).toBe(faCodeMerge);
    expect(merge.adapter.editor).toBeNull();
    expect(merge.adapter.container.nodeWidth).toBe(50);
    expect(merge.adapter.container.nodeHeight).toBe(180);
    expect(merge.adapter.container.noContent).toBe(true);
  });
});
