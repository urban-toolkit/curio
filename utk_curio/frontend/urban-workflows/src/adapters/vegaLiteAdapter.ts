/**
 * VegaLiteAdapter: GrammarAdapter implementation for Vega-Lite visualizations.
 *
 * Wraps the Vega-Lite compile + Vega View creation logic that was previously
 * embedded inside useVega / VegaNode. This adapter can be used standalone or
 * via the grammar adapter registry.
 */

import { GrammarAdapter, registerGrammarAdapter } from '../registry/grammarAdapter';
import { prepareVegaInput } from '../utils/vegaInput';

const vega = require('vega');
const lite = require('vega-lite');

export const vegaLiteAdapter: GrammarAdapter = {
  grammarId: 'vega-lite',

  async render(
    container: HTMLElement,
    spec: unknown,
    data?: unknown,
  ): Promise<void> {
    const specObj = typeof spec === 'string' ? JSON.parse(spec as string) : { ...spec as any };
    const inputData = data as any;

    // Shares the node's input path so the two cannot drift apart -- geometry
    // resolution included.
    const { values } = await prepareVegaInput(inputData, specObj);
    specObj.data = { values, name: 'data' };
    specObj.height = 'container';
    specObj.width = 'container';

    const vegaSpec = lite.compile(specObj).spec;
    const view = new vega.View(vega.parse(vegaSpec))
      .logLevel(vega.Warn)
      .renderer('svg')
      .initialize(container)
      .hover();

    await view.runAsync();
    return view;
  },

  getDefaultSpec(): unknown {
    return {
      $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
      mark: 'point',
      encoding: {
        x: { field: 'x', type: 'quantitative' },
        y: { field: 'y', type: 'quantitative' },
      },
    };
  },
};

registerGrammarAdapter(vegaLiteAdapter);
