/**
 * The Description modal says how many ports a kind has (#528).
 *
 * It printed the first port's cardinality as the port count, so Spatial Join,
 * two inputs of cardinality "1", read "Input number: 1" with
 * "GEODATAFRAME, GEODATAFRAME" as the types of that one input, while its own
 * description spoke of two input handles.
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
  test('several ports: the count, then each port with its types', () => {
    expect(describePorts(mockDescriptor.inputPorts, 'Input'))
      .toEqual(['Input number: 2', 'Input 1: GEODATAFRAME', 'Input 2: GEODATAFRAME']);
  });

  test("a port's cardinality shows when it is not one connection", () => {
    expect(describePorts([{ cardinality: '[1,n]', types: ['DATAFRAME'] }, { types: ['JSON'] }], 'Input'))
      .toEqual(['Input number: 2', 'Input 1 ([1,n]): DATAFRAME', 'Input 2: JSON']);
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
    expect(screen.getByText('Input 1: GEODATAFRAME')).toBeInTheDocument();
    expect(screen.getByText('Input 2: GEODATAFRAME')).toBeInTheDocument();
    expect(screen.getByText('Output number: 1')).toBeInTheDocument();
    expect(screen.queryByText('Input number: 1')).toBeNull();
  });
});
