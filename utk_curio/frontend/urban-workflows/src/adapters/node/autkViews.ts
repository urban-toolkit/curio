/**
 * An Autark node's views, as its run reads them: a list of maps and a list of
 * plots, each in a pane of its own and known by the key autk-grammar knows it
 * by.
 *
 * A document's `map` and `plot` are each one object or a list; either way the
 * run reads a list (`mapEntries`, `plotEntries`), in the document's order,
 * which is the order autk-grammar draws them in (its `maps`). The grammar's
 * `arrangeViews` gives each view its pane, in that order, maps first, and the
 * key the grammar knows it by (`ViewPane.key`): a map's `id`, else its index,
 * autk-grammar's `MapId`, which its `map:picking` events name a map by and its
 * calls that address one map (`highlightOnMap`, `mapLayer`, ...) take, a
 * string by `id` and a number by index; a plot's `id`, else its `dataRef`,
 * which its `plot:selection` events name it by and its plot calls take. The
 * run reads every key from the panes of the document it ran (`mapKey`,
 * `plotKey`).
 *
 * Every per-view step of a run reads them here: each view's pane and element
 * (`layOutPanes`, `viewTargets`), the selections each view receives
 * (`receivedByView`) and what each lights, on its own map or plot alone
 * (`lightViews`), a pick read from the map that picked
 * (`autkMapState.pickOn`), a brush from the plot that brushed (`plotEntryOf`),
 * the views a redraw keeps (`autkMapView.keepMapViews`) and a raster's edges
 * bled on each map (`autkRasters.bleedRasterEdges`).
 */
import type { ViewArrangement, ViewPane } from '@urban-toolkit/autk-grammar';
import { autkViewProblem } from '../../contracts/autkGrammar';
import { autkWorkspaceOf } from './autkDataCompile';

/** A document's views as autk-grammar's `arrangeViews` places them: one pane per view, maps first. */
export type ViewPanes = readonly ViewPane[];

/**
 * The links of *spec* that name views and layers it draws: those the grammar
 * wires. A run that leaves out a plot or a layer whose table it does not have
 * leaves out the links to it too, which autk-grammar would refuse.
 */
export function linksAtHand(spec: any): any[] {
    const links: any[] = Array.isArray(spec?.links) ? spec.links : [];
    return links.filter((link) => autkViewProblem({ map: spec?.map, plot: spec?.plot, links: [link] }) === null);
}

/**
 * The workspace of the views of *spec* that draw the table *layer*: the first
 * map whose layers name it, else the first plot of it, else the first view.
 */
export function workspaceOfLayer(spec: any, layer: string | undefined): string | undefined {
    const map = mapEntries(spec).find((entry) =>
        (Array.isArray(entry?.layerRefs) ? entry.layerRefs : []).some((ref: any) => ref?.dataRef === layer));
    if (map) return autkWorkspaceOf(map);
    const plot = plotEntries(spec).find((entry) => entry?.dataRef === layer);
    return autkWorkspaceOf(plot ?? mapEntries(spec)[0] ?? plotEntries(spec)[0]);
}

/** *value* as a list: none is an empty list, and one object a list of one. */
function asList(value: unknown): any[] {
    if (value === undefined || value === null) return [];
    return Array.isArray(value) ? value : [value];
}

/** The maps *spec* draws, in its order: a `map` written as one object is the one entry. */
export function mapEntries(spec: any): any[] {
    return asList(spec?.map);
}

/** The plots *spec* draws, in its order: a `plot` written as one object is the one entry. */
export function plotEntries(spec: any): any[] {
    return asList(spec?.plot);
}

/** The pane *panes* gives view *index* of kind *kind*, or undefined. */
function paneOf(panes: ViewPanes | null | undefined, kind: 'map' | 'plot', index: number): ViewPane | undefined {
    return (panes ?? []).find((pane) => pane.kind === kind && pane.index === index);
}

/** The key autk-grammar knows map *index* by, from the panes of its document: its `id`, else its index. */
export function mapKey(panes: ViewPanes | null | undefined, index: number): string | number {
    return paneOf(panes, 'map', index)?.key ?? index;
}

/** The key autk-grammar knows plot *index* by, from the panes of its document: its `id`, else its `dataRef`. */
export function plotKey(panes: ViewPanes | null | undefined, index: number): string | undefined {
    const key = paneOf(panes, 'plot', index)?.key;
    return key === undefined ? undefined : String(key);
}

/**
 * The index of the map *mapId* names among *panes*, as autk-grammar addresses
 * one: a number by its index, a string by its `id`; -1 when it names none.
 */
export function mapIndexOf(panes: ViewPanes | null | undefined, mapId: unknown): number {
    const maps = (panes ?? []).filter((pane) => pane.kind === 'map');
    if (typeof mapId === 'number') return maps.some((pane) => pane.index === mapId) ? mapId : -1;
    if (typeof mapId === 'string') return maps.find((pane) => pane.id === mapId)?.index ?? -1;
    return -1;
}

/**
 * The plot of *spec* that *plotId* names (its `id`, else its `dataRef`), by
 * the panes of *spec*, with its index; null when it names none.
 */
export function plotEntryOf(spec: any, panes: ViewPanes | null | undefined, plotId: unknown): { index: number; entry: any } | null {
    const pane = (panes ?? []).find((each) => each.kind === 'plot' && each.key === plotId);
    const entry = pane ? plotEntries(spec)[pane.index] : undefined;
    return pane && entry !== undefined ? { index: pane.index, entry } : null;
}

/**
 * The element id of view *index* of kind *kind* in node *nodeId*: the first
 * map draws on `autk-grammar-map-<node>`, map k on `autk-grammar-map-<node>-<k>`,
 * and plots likewise. e2e paints every canvas whose id starts
 * `autk-grammar-map-` into its captures.
 */
export function viewElementId(nodeId: string, kind: 'map' | 'plot', index: number): string {
    const id = `autk-grammar-${kind}-${nodeId}`;
    return index === 0 ? id : `${id}-${index}`;
}

/** What a run made for its views: each view's element, by its kind and index, and each map's canvas. */
export type LaidOutViews = {
    /** The element view `index` of `kind` draws in. */
    element: (kind: 'map' | 'plot', index: number) => HTMLElement | null;
    /** The canvases the maps draw on, in map order. */
    canvases: HTMLCanvasElement[];
};

/** The element a view of *kind* draws in: a canvas for a map, a div that scrolls a plot larger than it. */
function viewElement(nodeId: string, kind: 'map' | 'plot', index: number): HTMLElement {
    const element = document.createElement(kind === 'map' ? 'canvas' : 'div');
    element.id = viewElementId(nodeId, kind, index);
    element.style.cssText = kind === 'map'
        ? 'display:block;width:100%;height:100%;'
        : 'width:100%;height:100%;overflow:auto;';
    return element;
}

/**
 * Put the views of *arrangement* in *wrapper*, emptied first, each in the
 * element it draws in. One view fills the wrapper. Several views each get a
 * pane, placed where autk-grammar's `arrangeViews` says: a grid of its `rows`
 * and `columns`, `gap` pixels apart, each pane at its `row` and `column`. A
 * pane is positioned, since autk-map puts a map's menu, legend and watermark
 * in its canvas's parent, and holds the view's `id`, when it has one, in
 * `data-view-id`.
 */
export function layOutPanes(wrapper: HTMLElement, nodeId: string, arrangement: ViewArrangement): LaidOutViews {
    while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);
    const elements = new Map<string, HTMLElement>();
    const canvases: HTMLCanvasElement[] = [];
    const several = arrangement.panes.length > 1;
    const holder = several ? document.createElement('div') : wrapper;
    if (several) {
        holder.dataset.curioAutkViews = String(arrangement.panes.length);
        holder.style.cssText = [
            'display:grid', 'width:100%', 'height:100%',
            `grid-template-columns:repeat(${arrangement.columns}, minmax(0, 1fr))`,
            `grid-template-rows:repeat(${Math.max(arrangement.rows, 1)}, minmax(0, 1fr))`,
            `gap:${arrangement.gap}px`,
        ].join(';');
        wrapper.appendChild(holder);
    }
    for (const pane of arrangement.panes) {
        const element = viewElement(nodeId, pane.kind, pane.index);
        if (pane.id !== undefined) element.dataset.viewId = pane.id;
        if (several) {
            const slot = document.createElement('div');
            slot.dataset.curioAutkPane = `${pane.kind}-${pane.index}`;
            if (pane.id !== undefined) slot.dataset.viewId = pane.id;
            slot.style.cssText = [
                'position:relative', 'overflow:hidden', 'min-width:0', 'min-height:0',
                `grid-row:${pane.row + 1}`, `grid-column:${pane.column + 1}`,
            ].join(';');
            slot.appendChild(element);
            holder.appendChild(slot);
        } else {
            holder.appendChild(element);
        }
        elements.set(`${pane.kind}:${pane.index}`, element);
        if (pane.kind === 'map') canvases[pane.index] = element as HTMLCanvasElement;
    }
    return {
        element: (kind, index) => elements.get(`${kind}:${index}`) ?? null,
        canvases: canvases.filter(Boolean),
    };
}

/**
 * The targets autk-grammar draws *spec*'s views in: the element of each map
 * and plot the run hands it, in its order, by the view's index in the
 * document as written (*kept*): one element is its id, several a list.
 */
export function viewTargets(
    nodeId: string,
    kept: { maps: readonly number[]; plots: readonly number[] },
): Record<string, string | string[]> {
    const targets: Record<string, string | string[]> = {};
    for (const kind of ['map', 'plot'] as const) {
        const ids = (kind === 'map' ? kept.maps : kept.plots).map((index) => viewElementId(nodeId, kind, index));
        if (ids.length > 0) targets[kind] = ids.length === 1 ? ids[0] : ids;
    }
    return targets;
}

/** The table of the map *entry*'s own picking layer: its first layer that picks (`isPick`), else its first. */
export function pickLayerOf(entry: any): string | undefined {
    const refs: any[] = Array.isArray(entry?.layerRefs) ? entry.layerRefs : [];
    return refs.find((ref) => ref?.isPick)?.dataRef ?? refs[0]?.dataRef;
}

/** A view a selection was made in: a map or a plot of the document, by its place among the views of its kind. */
export type DrawnView = { kind: 'map' | 'plot'; index: number; entry: any };

/** A layer a map of the document draws, with the map's index and entry. */
export type MapLayerRef = { index: number; entry: any; ref: any };

/** Every layer each map of *spec* draws, the maps in order and each map's layers in order. */
export function mapLayerRefs(spec: any): MapLayerRef[] {
    return mapEntries(spec).flatMap((entry, index) =>
        (Array.isArray(entry?.layerRefs) ? entry.layerRefs : []).map((ref: any) => ({ index, entry, ref })));
}

/**
 * The selections a node receives (`data.interactions`), by the view each is
 * for: those delivered on the node's own dot, for every view (`whole`), and
 * those delivered on a view's dot (`toView`, providers/flow/interactionRoutes),
 * for that view alone, by its pane (`<kind>:<index>`). A node of one view
 * takes a delivery on any dot as its own; a node of several drops one for a
 * view it does not have.
 */
export function receivedByView<T extends { toView?: unknown }>(
    incoming: readonly T[],
    panes: ViewPanes | null | undefined,
): { whole: T[]; byView: Map<string, T[]> } {
    const all = panes ?? [];
    const whole: T[] = [];
    const byView = new Map<string, T[]>();
    for (const selection of incoming) {
        const view = typeof selection?.toView === 'string' ? selection.toView : null;
        if (view === null || all.length <= 1) {
            whole.push(selection);
            continue;
        }
        const pane = all.find((each) => each.id === view);
        if (!pane) continue;
        const key = `${pane.kind}:${pane.index}`;
        byView.set(key, [...(byView.get(key) ?? []), selection]);
    }
    return { whole, byView };
}

/** What a view of a node lights: a table on one of its maps, by the map's index, or one of its plots, by its key. */
export type LitView =
    | { kind: 'map'; index: number; table: string; positions: number[] }
    | { kind: 'plot'; plot: string; positions: number[] };

const litKey = (view: LitView): string =>
    view.kind === 'map' ? `map:${view.index}:${view.table}` : `plot:${view.plot}`;

/**
 * Ask *grammar* to light each of *views* that lights other positions than it
 * did when it was last asked, by *lit* (each view's positions, by its key; a
 * view it holds nothing of is asked as one never lit): each map's table on its
 * own map alone, by the map's index, so two maps of one table light only
 * their own rows, and each plot by its key. Every clear comes before any
 * light. autk-grammar carries a selection set on a plot to the map layers its
 * `links` join it to, and one lit on a map to the plots linked to it, so a
 * view whose own positions did not change is not asked again, and a clear
 * never undoes what a view's light carried on to another.
 */
export function lightViews(grammar: any, views: readonly LitView[], lit: Map<string, string>): void {
    const asked = new Map<string, LitView>();
    for (const view of views) if (!asked.has(litKey(view))) asked.set(litKey(view), view);
    const changed = [...asked.values()].filter((view) => lit.get(litKey(view)) !== JSON.stringify(view.positions));
    const call = (view: LitView) => {
        if (view.kind === 'map') {
            if (view.positions.length === 0) grammar?.clearHighlightOnMap?.(view.table, view.index);
            else grammar?.highlightOnMap?.(view.table, view.positions, view.index);
        } else if (view.positions.length === 0) {
            grammar?.clearHighlightOnPlot?.(view.plot);
        } else {
            grammar?.setPlotSelection?.(view.plot, view.positions);
        }
    };
    for (const view of changed) if (view.positions.length === 0) call(view);
    for (const view of changed) if (view.positions.length > 0) call(view);
    for (const view of changed) lit.set(litKey(view), JSON.stringify(view.positions));
}
