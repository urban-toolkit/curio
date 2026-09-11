/**
 * Regression test for #187 — the Provenance graph could not be panned or zoomed.
 *
 * ModalShell puts React Flow's own opt-out classes on the dialog element
 * (`components/ModalShell.tsx`: `${styles.modal} nowheel nodrag nopan`), and
 * React Flow's gesture filter matches them by ANCESTOR:
 *
 *     const isWrappedWithClass = (event, className) =>
 *         event.target.closest(`.${className}`);
 *
 * (@reactflow/core dist, the d3-zoom filter). So every mousedown and wheel
 * inside the modal found the `.nopan` / `.nowheel` ancestor and was refused,
 * leaving only the <Controls> buttons — which call zoomIn/fitView imperatively.
 * Nodes below the fold were unreachable, exactly as reported.
 *
 * jsdom has no layout engine, so this asserts the contract that makes the
 * gestures work rather than the gestures themselves: the inner ReactFlow must
 * name opt-out classes that nothing inside it carries. The sibling
 * `components/editing/NodeProvenance.tsx` already does this and documents why.
 */
import React from 'react';
import { render } from '@testing-library/react';

const rfProps: Record<string, any> = {};

jest.mock('reactflow', () => ({
  __esModule: true,
  default: (props: any) => {
    Object.assign(rfProps, props);
    return <div data-testid="inner-reactflow" />;
  },
  ReactFlowProvider: ({ children }: any) => <>{children}</>,
  Controls: () => <div />,
  Handle: () => <div />,
  BaseEdge: () => <div />,
  Position: { Top: 'top', Bottom: 'bottom' },
  useStore: () => undefined,
  getSmoothStepPath: () => ['M0,0'],
}));

jest.mock('../../hook/useCode', () => ({
  useCode: () => ({ loadTrill: jest.fn() }),
}));

import TrillProvenanceWindow from '../../components/menus/provenance/TrillProvenanceWindow';
import { TrillGenerator } from '../../TrillGenerator';

beforeEach(() => {
  for (const k of Object.keys(rfProps)) delete rfProps[k];
  TrillGenerator.reset();
  // The graph only renders with at least one version; otherwise the component
  // short-circuits to "No versions yet" and never mounts a ReactFlow at all.
  TrillGenerator.provenanceJSON = {
    id: 'wf',
    nodes: [
      { id: 'v1', label: 'v1', timestamp: 1, preview: { nodes: [], edges: [] } },
      { id: 'v2', label: 'v2', timestamp: 2, preview: { nodes: [], edges: [] } },
    ],
    edges: [{ id: 'v1_to_v2', source: 'v1', target: 'v2' }],
  };
});

const renderWindow = () =>
  render(
    <TrillProvenanceWindow open closeModal={jest.fn()} workflowName="wf" />,
  );

describe('TrillProvenanceWindow pan/zoom inside ModalShell (#187)', () => {
  test('the inner graph opts out of the modal wrapper\'s nopan/nowheel', () => {
    renderWindow();

    // Must differ from React Flow's defaults ('nopan' / 'nowheel'), which is what
    // ModalShell's dialog carries.
    expect(rfProps.noPanClassName).toBe('inner-nopan');
    expect(rfProps.noWheelClassName).toBe('inner-nowheel');
    expect(rfProps.noPanClassName).not.toBe('nopan');
    expect(rfProps.noWheelClassName).not.toBe('nowheel');
  });

  test('nothing the modal renders carries the inner opt-out classes', () => {
    const { baseElement } = renderWindow();

    expect(baseElement.querySelector('.inner-nopan')).toBeNull();
    expect(baseElement.querySelector('.inner-nowheel')).toBeNull();
    // ...while the blocking ancestor really is there, which is the whole problem.
    expect(baseElement.querySelector('.nopan')).not.toBeNull();
  });

  test('fitView can frame a tall chain — minZoom is below the 0.5 default', () => {
    renderWindow();

    expect(rfProps.fitView).toBe(true);
    expect(rfProps.minZoom).toBeLessThan(0.5);
  });
});
