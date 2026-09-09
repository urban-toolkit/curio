# Icon Source Map

The PNG concepts now use repo-backed Curio icons where the current app already defines them.

## Source Files

- Built-in node definitions: `packages/curio.builtin@1/manifest.json`
- Curio icon registry: `utk_curio/frontend/urban-workflows/src/registry/iconRegistry.ts`
- Top menu references: `utk_curio/frontend/urban-workflows/src/components/menus/top/UpMenu.tsx`
- Built-in palette rendering: `utk_curio/frontend/urban-workflows/src/components/menus/nodes/ToolsMenu.tsx`
- Font Awesome modules: `utk_curio/frontend/urban-workflows/node_modules/@fortawesome`

## Built-In Palette Icons

| Concept label | Curio built-in node | Repo icon ref |
| --- | --- | --- |
| Load | Data Loading | `fa-solid:upload` |
| Export | Data Export | `fa-solid:download` |
| Transform | Data Transformation | `fa-solid:database` |
| Spatial | Spatial Join | `fa-solid:object-group` |
| Merge | Merge Flow | `fa-solid:code-merge` |
| Pool | Data Pool | `fa-solid:server` |
| Python | Python Computation | `fa-brands:python` |
| Summary | Data Summary | `fa-solid:rectangle-list` |
| JavaScript | JS Computation | `fa-brands:js` |
| Autark | Autark | `fa-solid:city` + `AUTK` manifest badge |
| Vega | Vega-Lite | `fa-solid:chart-line` + `VEGA` manifest badge |
| View | Simple View | `fa-solid:table` |

## Common UI Icons

| UI location | Repo icon ref or asset |
| --- | --- |
| Curio top-left logo | `utk_curio/frontend/urban-workflows/src/assets/curio-2.png` |
| AI / agent top-bar toggle | `fa-solid:robot` |
| Saved state | `fa-solid:floppy-disk` |
| Save toolbar action | `fa-solid:floppy-disk` |
| Share result action | `fa-solid:share-nodes` |
| Run toolbar action | `fa-solid:play` |
| Refresh toolbar action | `fa-solid:rotate-right` |
| Palette run-all button | `fa-solid:forward-step` |
| Search field | `fa-solid:magnifying-glass` |
| Agent/catalog settings entry | `fa-solid:gear` |
| Attachment settings entry | `fa-solid:gear` |
| Node footer menu | `fa-solid:bars` |
| Node footer code action | `fa-solid:code` |

The gear identifies the shared settings shell; it is not a standalone label. The drawer exposes
`Agent settings` for account policy. An owned My Imports detail exposes `Definition settings for
<agent>` for prompt governance. An Installed in this project detail exposes `Project agent
settings` for that project's materialized defaults, and unified chat exposes `Attachment settings`
for tightening overrides. All controls require a visible label where space permits, a tooltip, an
accessible name, `aria-haspopup="dialog"`, and a stable pointer target. Draggable project AGENTS
palette rows do not show a gear. The shared result shows no settings icon or private
resource control.

The share icon always opens flow/Trill result sharing; it never means share an agent definition,
import, project template, attachment, chat, or editable/executable project. Agent-private data is
not exposed in the shared result, and the public result view shows no private resource controls,
settings, execution, `Save a copy`, or project clone.

## Agent-Specific Icons

Agent Catalog items and attached-agent dock tiles continue to use the concept-specific bot-head
icon. This is intentional: Curio does not currently have a production icon family for hookable
agents, and the bot-head shape distinguishes agents from built-in nodes, datasets, and packages.
