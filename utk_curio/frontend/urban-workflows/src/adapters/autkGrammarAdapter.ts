import { GrammarAdapter, registerGrammarAdapter } from '../registry/grammarAdapter';

const DEFAULT_SPEC = JSON.stringify(
  {
    data: [
      {
        type: 'osm',
        outputTableName: 'osm_surface',
        queryArea: { geocodeArea: 'Chicago', areas: ['Loop'] },
        autoLoadLayers: {
          coordinateFormat: 'EPSG:3395',
          layers: ['surface'],
          dropOsmTable: true,
        },
      },
    ],
    map: {
      layerRefs: [{ dataRef: 'osm_surface' }],
    },
  },
  null,
  2,
);

export const autkGrammarAdapter: GrammarAdapter = {
  grammarId: 'autk-grammar',

  validate(spec: unknown): boolean {
    try {
      const parsed = typeof spec === 'string' ? JSON.parse(spec) : spec;
      return parsed != null && typeof parsed === 'object' && !Array.isArray(parsed);
    } catch {
      return false;
    }
  },

  // render is not called for autk-grammar — applyGrammar in the lifecycle
  // drives execution directly via AutkGrammar.run(). This stub satisfies
  // the GrammarAdapter interface contract.
  async render(_container: HTMLElement, _spec: unknown, _data?: unknown): Promise<void> {},

  getDefaultSpec(): unknown {
    return DEFAULT_SPEC;
  },
};

registerGrammarAdapter(autkGrammarAdapter);
