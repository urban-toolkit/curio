/**
 * UTKAdapter: GrammarAdapter implementation for Urban Toolkit (UTK) visualizations.
 *
 * Due to UTK's complexity (serverless layers, GrammarInterpreter lifecycle,
 * interaction callbacks), the actual render logic remains in the useUTK hook.
 * This adapter provides the standard GrammarAdapter interface for registration
 * and basic validate/getDefaultSpec operations.
 *
 * Full render integration with GrammarVisBox is deferred to Phase 6.
 */

import { GrammarAdapter, registerGrammarAdapter } from '../registry/grammarAdapter';

export const utkAdapter: GrammarAdapter = {
  grammarId: 'utk',

  validate(spec: unknown): boolean {
    try {
      const parsed = typeof spec === 'string' ? JSON.parse(spec) : spec;
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed);
    } catch {
      return false;
    }
  },

  async render(
    container: HTMLElement,
    spec: unknown,
    data?: unknown,
    options?: { interactions?: unknown; resolutionMode?: string },
  ): Promise<void> {
    // UTK rendering is managed by useUTK hook due to complex lifecycle.
    // This method is a placeholder for future full extraction.
    console.warn('UTK render via adapter is not yet fully extracted — use useUTK hook directly.');
  },

  getDefaultSpec(): unknown {
    return {
      components: [],
      grid: {
        width: 0,
        height: 0,
      },
      knots: [],
      map_style: [],
    };
  },
};

registerGrammarAdapter(utkAdapter);
