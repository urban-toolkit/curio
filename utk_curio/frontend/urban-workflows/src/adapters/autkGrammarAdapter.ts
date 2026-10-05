import { GrammarAdapter, registerGrammarAdapter } from '../registry/grammarAdapter';

export const autkGrammarAdapter: GrammarAdapter = {
  grammarId: 'autk-grammar',

  // render is not called for autk-grammar — applyGrammar in the behavior
  // drives execution directly via AutkGrammar.run(). This stub satisfies
  // the GrammarAdapter interface contract.
  async render(_container: HTMLElement, _spec: unknown, _data?: unknown): Promise<void> {},
};

registerGrammarAdapter(autkGrammarAdapter);
