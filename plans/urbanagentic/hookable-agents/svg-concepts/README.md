# SVG Concepts (Figma-ready)

Vector twins of the twenty screens in `../png-concepts/`, generated from the same
renderer so layout, spacing, typography, and component structure match the PNGs
exactly. Each is a 1672 × 941 frame. The set reflects the finalized model (three-scope
lifecycle drawer, project-scoped `Install in project` with no auto-install, the six
governed settings screens plus a scope-applicability matrix, and node Explanation-tab
removal); agents use the system's **existing** sharing behavior, so there is no dedicated
agent-sharing screen.

1. `01-agents-catalog-drawer.svg`
2. `02-main-dataflow-attached-agents.svg`
3. `03-attachment-dataset-finder-to-data-load.svg`
4. `04-attachment-node-explainer-to-node.svg`
5. `05-attachment-dataflow-builder-to-canvas.svg`
6. `06-agent-refinement-sidebar-open.svg`
7. `07-dataset-finder-overview.svg`
8. `08-dataset-review-modal.svg`
9. `09-datasets-created-in-palette.svg`
10. `10-dataflow-builder-orchestration.svg`
11. `11-agents-palette.svg`
12. `12-agent-settings-cost.svg`
13. `13-agent-settings-quotas.svg`
14. `14-agent-settings-resource-policies.svg`
15. `15-agent-settings-prompt-quality.svg`
16. `16-agent-settings-prompt-editor.svg`
17. `17-agent-settings-prompt-audit.svg`
18. `18-agents-drawer-lifecycle.svg`
19. `19-settings-scope-applicability.svg`
20. `20-node-explainer-only-workflow.svg`

Text is real `<text>` (Rubik for UI, Roboto Mono for node code); icons are
Font Awesome `<path>` vectors; shapes are SVG primitives — all editable in Figma.
Enable the Rubik and Roboto Mono Google Fonts in Figma before importing.

See `../figma-ready/` for the import manifest and design tokens. Regenerate with:

```bash
python3 ../sources/render_hookable_agents_png_concepts.py svg
```
