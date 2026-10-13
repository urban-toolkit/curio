/**
 * The Description modal says how many ports a kind has (#528).
 *
 * It printed the first port's cardinality as the port count, so Spatial Join,
 * two inputs of cardinality "1", read "Input number: 1" with
 * "GEODATAFRAME, GEODATAFRAME" as the types of that one input, while its own
 * description spoke of two input handles.
 *
 * The inputs are numbered from 0, as their circles, their chips
 * (`[!! input_0 !!]`) and the Spatial Join's own text count them (#576
 * follow-up): its body says input_0 and input_1, so the description must not
 * call them Input 1 and Input 2.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import DescriptionModal, { describePorts } from '../../components/DescriptionModal';
import type { NodeTemplateId } from '../../registry/types';

// Spatial Join's ports, as packages/curio.builtin@1/manifest.json declares them.
const mockDescriptor = {
  label: 'Spatial Join',
  inputPorts: [
    { cardinality: '1', types: ['GEODATAFRAME'] },
    { cardinality: '1', types: ['GEODATAFRAME'] },
  ],
  outputPorts: [{ cardinality: '1', types: ['GEODATAFRAME'] }],
  hasCode: true,
  hasWidgets: false,
  hasGrammar: false,
  description: 'Two input handles on its left edge.',
};

// The registry index loads every adapter, and with them vega's ESM build.
jest.mock('../../registry', () => ({ getNodeDescriptor: () => mockDescriptor }));

describe('describePorts', () => {
  test('several ports: the count, then each port with its types, numbered from 0 as the circles are', () => {
    expect(describePorts(mockDescriptor.inputPorts, 'Input'))
      .toEqual(['Input number: 2', 'Input 0: GEODATAFRAME', 'Input 1: GEODATAFRAME']);
  });

  test("a port's cardinality shows when it is not one connection", () => {
    expect(describePorts([{ cardinality: '[1,n]', types: ['DATAFRAME'] }, { types: ['JSON'] }], 'Input'))
      .toEqual(['Input number: 2', 'Input 0 ([1,n]): DATAFRAME', 'Input 1: JSON']);
  });

  test('one port reads as it always has', () => {
    expect(describePorts([{ cardinality: '[1,n]', types: ['DATAFRAME', 'GEODATAFRAME'] }], 'Output'))
      .toEqual(['Output number: [1,n]', 'Supported output types: DATAFRAME, GEODATAFRAME']);
  });

  test('no ports', () => {
    expect(describePorts([], 'Output')).toEqual(['Output number: N/A']);
  });
});

describe('DescriptionModal', () => {
  test('a kind with two inputs says it has two', () => {
    render(
      <DescriptionModal
        nodeId="n1"
        nodeType={'curio.builtin/spatial-join@1' as NodeTemplateId}
        show
        handleClose={() => {}}
      />,
    );
    expect(screen.getByText('Input number: 2')).toBeInTheDocument();
    expect(screen.getByText('Input 0: GEODATAFRAME')).toBeInTheDocument();
    expect(screen.getByText('Input 1: GEODATAFRAME')).toBeInTheDocument();
    expect(screen.queryByText('Input 2: GEODATAFRAME')).toBeNull();
    expect(screen.getByText('Output number: 1')).toBeInTheDocument();
    expect(screen.queryByText('Input number: 1')).toBeNull();
  });
});

// #225: the description is what a user reads to learn the node, so it renders
// as text people write (markdown), and comes before the technical lines.
describe('DescriptionModal description text', () => {
  const original = mockDescriptor.description;
  afterEach(() => {
    mockDescriptor.description = original;
  });

  function renderModal() {
    return render(
      <DescriptionModal
        nodeId="n1"
        nodeType={'curio.builtin/spatial-join@1' as NodeTemplateId}
        show
        handleClose={() => {}}
      />,
    );
  }

  test('code formatting renders as code, not as backticks', () => {
    mockDescriptor.description = 'Pick the `name` column.';
    renderModal();
    const container = document.body;
    expect(container.querySelector('code')?.textContent).toBe('name');
    expect(container.textContent).not.toContain('`');
  });

  test('a link or raw HTML in a description is not rendered', () => {
    mockDescriptor.description = 'See [the docs](https://example.org) and <b>this</b>.';
    renderModal();
    const container = document.body;
    expect(container.querySelector('a')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
  });

  test('the description comes before the port lines', () => {
    mockDescriptor.description = 'Finds the polygon each point falls in.';
    renderModal();
    const container = document.body;
    const text = container.textContent ?? '';
    expect(text.indexOf('Finds the polygon')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('Finds the polygon')).toBeLessThan(text.indexOf('Input number: 2'));
  });
});
