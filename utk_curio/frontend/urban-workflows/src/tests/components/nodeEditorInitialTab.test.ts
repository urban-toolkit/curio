/**
 * Regression test for the third strand of #157: which tab a node's editor opens on.
 *
 * `activeTab` was hardcoded to "code". autk-grammar and vis-vega both declare
 * `hasCode: false` in curio.builtin@1's manifest, so for those kinds NO pane was
 * active on mount and the grammar Monaco was created inside a `display: none`
 * Bootstrap tab-pane, at zero size.
 */
import { resolveInitialEditorTab } from '../../utils/canvasTemplateConfig';

describe('resolveInitialEditorTab', () => {
  test('a code node opens on code', () => {
    expect(resolveInitialEditorTab({ code: true, grammar: false, widgets: true })).toBe('code');
  });

  test('a grammar-only node opens on grammar, not the missing code pane', () => {
    // The autk-grammar / vis-vega shape: hasCode:false, hasGrammar:true.
    expect(resolveInitialEditorTab({ code: false, grammar: true, widgets: true })).toBe('grammar');
  });

  test('code wins when a kind somehow declares both', () => {
    expect(resolveInitialEditorTab({ code: true, grammar: true, widgets: false })).toBe('code');
  });

  test('falls back through widgets to output so the tab always exists', () => {
    expect(resolveInitialEditorTab({ code: false, grammar: false, widgets: true })).toBe('widgets');
    expect(resolveInitialEditorTab({ code: false, grammar: false, widgets: false })).toBe('output');
  });

  test('a node with neither code nor a spec opens on what it shows, its widgets a tab away', () => {
    // Simple View's shape: hasCode:false, hasGrammar:false, hasWidgets:true, and its cards.
    expect(resolveInitialEditorTab({ code: false, grammar: false, widgets: true, output: true })).toBe('output');
    // Code or a spec still come first, and a template that opens on its controls still does.
    expect(resolveInitialEditorTab({ code: true, grammar: false, widgets: true, output: true })).toBe('code');
    expect(resolveInitialEditorTab({ code: false, grammar: true, widgets: true, output: true })).toBe('grammar');
    expect(
      resolveInitialEditorTab({ code: true, grammar: false, widgets: true, widgetsFirst: true, output: true }),
    ).toBe('widgets');
  });
});
