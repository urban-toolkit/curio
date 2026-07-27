# PNG Concepts

These twenty PNGs are presentation-ready concept screens for the Hookable Agents UI,
regenerated to the finalized model: the three-scope lifecycle drawer (Global Catalog /
My Imports / Installed in this project), project-scoped `Install in project` with no
auto-install, the six governed agent settings screens plus a scope-applicability matrix,
and the removal of the node Explanation tab. Agents use the system's **existing** sharing
behavior; there is no dedicated agent-sharing screen. They use the current Curio workspace
as the visual baseline. Where a text specification and an image differ, the specification
is authoritative.

The screens are generated through a supersampled renderer so icons, text, node borders, shadows, and connector paths downsample cleanly. The top bar uses the live Curio logo asset and 65px menu-bar style from the current app reference.

Built-in palette and common UI icons are rendered from the same Font Awesome icon refs Curio uses in the frontend package manifest and menu components. Agent catalog entries still use the bot-head concept icon so agent affordances remain visually distinct.

## Screens

1. `01-agents-catalog-drawer.png`
   - Right sidebar `Agents Catalog` drawer, three-scope: Global Catalog / My Imports / Installed in this project.
   - Global Catalog active; cards expose `Install in project`; footer is `Import package`.
   - Emphasizes discovery, filtering, metadata, and selection.

2. `02-main-dataflow-attached-agents.png`
   - Main dataflow screen with multiple attached agents visible.
   - Shows node-level agents as icon-only dock tiles beneath their targets.
   - Shows Dataflow Builder as a canvas-level dock.

3. `03-attachment-dataset-finder-to-data-load.png`
   - Focused attachment example for `Dataset Finder -> Data Load node`.
   - Highlights the compatible Data Load hook.
   - Shows Dataset Finder suggesting external dataset APIs, endpoints, and public data portals.
   - Shows a selected NOAA source populating the Data Load node input.
   - Uses a green attachment path, source review drawer, and callout.

4. `04-attachment-node-explainer-to-node.png`
   - Focused attachment example for `Node Explainer -> node`.
   - Highlights the compute node as the compatible hook.
   - Uses a blue attachment path and selected target state.

5. `05-attachment-dataflow-builder-to-canvas.png`
   - Focused attachment example for `Dataflow Builder -> canvas`.
   - Shows a canvas-level boundary and the Dataflow Builder dock.
   - Uses orange to match Curio's selected/action accent.

6. `06-agent-refinement-sidebar-open.png`
   - Earlier refinement-sidebar concept for an attached Node Explainer agent.
   - Conversational refinement is now the unified chat drawer; cost/quota/resource and prompt-governance controls belong in dedicated settings screens.
   - Keeps the selected attached-agent dock tile visible on the canvas.

7. `07-dataset-finder-overview.png`
   - Earlier unified-chat history for Dataset Finder external-source and Data Catalog paths.

8. `08-dataset-review-modal.png`
   - Earlier Node Builder-generated data-load review concept; current review behavior remains in unified chat rather than a nested modal.

9. `09-datasets-created-in-palette.png`
   - Curio DATA palette treatment for externally sourced and catalog-installed datasets with provenance.

10. `10-dataflow-builder-orchestration.png`
    - Orchestration plan/status view; a missing specialist is added via a reviewed `Install in project` proposal, never auto-installed.

11. `11-agents-palette.png`
    - The active project's installed-template AGENTS palette; rows are action-free and draggable, and switching projects replaces the list.

12. `12-agent-settings-cost.png`
    - Governed agent settings modal (six-tab rail) — Cost: per-run/rolling budgets, usage meter, alert thresholds, pricing effective date, Estimated vs Actual labels.

13. `13-agent-settings-quotas.png`
    - Quotas: execution/token/tool/concurrency limits, reservations, reset window, and locked inherited values.

14. `14-agent-settings-resource-policies.png`
    - Resource policies: provider profile/model/locality (Local vs Remote), egress, context/output, timeout, tools/network; secrets never shown.

15. `15-agent-settings-prompt-quality.png`
    - Prompt quality: pinned suite/rubric/threshold, evaluation status, findings, and cost/usage.

16. `16-agent-settings-prompt-editor.png`
    - Prompt editor: owned My-Imports draft with variables/schema validation, diff, and `Save draft`; the immutable definition bytes are unchanged.

17. `17-agent-settings-prompt-audit.png`
    - Prompt audit: versioned privacy/security/compliance rules, findings, and append-only governance history distinct from the transcript.

18. `18-agents-drawer-lifecycle.png`
    - The lifecycle as a vertical flow across the three scopes: Import (private) → Publish → Global Catalog → Install in project → Installed → Attach.

19. `19-settings-scope-applicability.png`
    - Matrix of how each settings screen applies across Account policy, owned Imported definition, Project agent default, and Attached instance (own / inherit / read-only).

20. `20-node-explainer-only-workflow.png`
    - A node with no built-in Explanation tab; `Explain with Node Explainer` opens the normal install → attach → chat workflow, not a bespoke node panel.

## Regenerating

Run the renderer from the repository root:

```bash
python3 plans/urbanagentic/hookable-agents/sources/render_hookable_agents_png_concepts.py
```

The renderer overwrites only files in this `png-concepts` folder.
