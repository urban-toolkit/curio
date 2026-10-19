/**
 * Guard test for the #159 / #169 class of bug: a lookup keyed by the UNVERSIONED
 * `NodeType` enum, fed the VERSIONED id a palette drag actually produces.
 *
 * Both forms coexist in real canvases — a palette drag stores
 * `curio.builtin/data-pool@1`, the Jupyter converter and legacy trills store
 * `curio.builtin/data-pool`, and nothing normalizes them at load time. So
 * every unversioned-keyed map has to be read through a normalizer, or versioned
 * nodes silently take the fallback branch.
 *
 * This is deliberately a *parity* test rather than a test of one call site: it
 * asserts the two forms are indistinguishable to each lookup, which is the
 * property that keeps getting broken one call site at a time.
 */
import React from 'react';
import { render } from '@testing-library/react';

import type { GraphPreview } from '../../api/projectsApi';
import DataflowThumbnail from '../../components/DataflowThumbnail';
import { liveGraphPreview } from '../../components/scenarios/catalog/inProjectRows';
import { NodeType, CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';
import { CATEGORY_FALLBACK_FG } from '../../constants/nodeCategoryPalette';
import { TrillGenerator } from '../../TrillGenerator';
import {
  unversionedNodeType,
  getUnversionedFlowNodeType,
  getFlowNodeCanonicalType,
} from '../../utils/flowNodeCanonicalType';
import { registerShippedTemplates } from '../_support/categoryDescriptors';

const ALL_TYPES = Object.values(NodeType);
const versioned = (t: string, major = 1) => `${t}@${major}`;

describe('unversionedNodeType', () => {
  test.each(ALL_TYPES)('strips @major from %s', (type) => {
    expect(unversionedNodeType(versioned(type))).toBe(type);
    expect(unversionedNodeType(versioned(type, 7))).toBe(type);
  });

  test('leaves an already-unversioned id untouched', () => {
    ALL_TYPES.forEach((type) => expect(unversionedNodeType(type)).toBe(type));
  });

  test('leaves a non-canonical string untouched rather than mangling it', () => {
    // Not `<pkg>/<template>@<major>`, so there is no version to strip.
    expect(unversionedNodeType('__curioUniversalNode')).toBe('__curioUniversalNode');
    expect(unversionedNodeType('')).toBe('');
  });
});

describe('getUnversionedFlowNodeType', () => {
  test.each(ALL_TYPES)('normalizes both id forms of %s to the enum value', (type) => {
    // Shape of a real canvas node: RF `type` is the stable sentinel and the
    // dispatcher id lives in `data.nodeType` (see getFlowNodeCanonicalType).
    const bare = { type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeType: type } };
    const withVersion = {
      type: CURIO_UNIVERSAL_NODE_TYPE,
      data: { nodeType: versioned(type) },
    };

    expect(getUnversionedFlowNodeType(bare)).toBe(type);
    expect(getUnversionedFlowNodeType(withVersion)).toBe(type);
    // The un-normalized helper is what the buggy call sites used: it hands back
    // the `@1` verbatim, which is why `=== NodeType.X` failed.
    expect(getFlowNodeCanonicalType(withVersion)).toBe(versioned(type));
  });
});

describe('a preview colours both id forms alike', () => {
  // A preview built in the browser gives each node its registered
  // descriptor's category, and the registry holds versioned ids. A versioned
  // or unversioned miss is not a crash, it is a silently grey node: exactly
  // the kind of regression a type check cannot catch.
  const COLOURED: NodeType[] = [
    NodeType.DATA_LOADING,
    NodeType.DATA_TRANSFORMATION,
    NodeType.DATA_POOL,
    NodeType.VIS_VEGA,
  ];

  beforeAll(() => registerShippedTemplates('curio.builtin@1'));

  const canvasNode = (id: string, nodeType: string) => ({
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: id === 'bare' ? 0 : 300, y: 0 },
    data: { nodeId: id, nodeType },
  });

  /** The colour DataflowThumbnail paints each node of *preview* in. */
  const bars = (preview: GraphPreview) =>
    Array.from(render(React.createElement(DataflowThumbnail, { preview })).container.querySelectorAll('g'))
      .map((g) => g.querySelectorAll('rect')[1].getAttribute('fill'));

  test.each(COLOURED)('the live previews and DataflowThumbnail give %s the same colour either way', (type) => {
    const nodes = [canvasNode('bare', type), canvasNode('withVersion', versioned(type))];
    TrillGenerator.reset();
    TrillGenerator.addNewVersionProvenance(nodes, [], 'wf', '', 'Node added');
    const recorded = TrillGenerator.provenanceJSON.nodes.at(-1).preview as GraphPreview;

    for (const preview of [liveGraphPreview(nodes, []), recorded]) {
      const [bare, withVersion] = preview.nodes.map((n) => n.category);
      expect(bare).toBeTruthy();
      expect(withVersion).toBe(bare);

      const [bareFill, versionedFill] = bars(preview);
      expect(bareFill).not.toBe(CATEGORY_FALLBACK_FG);
      expect(versionedFill).toBe(bareFill);
    }
  });
});
