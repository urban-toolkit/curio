/**
 * An agent's drag on the canvas, as every tab plays it.
 *
 * An agent at work is a peer of the dataflow's doc, run by the server, with an
 * awareness state of its own: its `user` names it and holds its `agent`, with
 * its `category`. While it drags something onto the canvas, its state holds
 *
 * - `carrying`: `{id, kind, from, onto, node: {type, label}, ms}`, the drag;
 * - `pointer`: `{x, y, t}` in flow coordinates (`cursors.ts`), its drop point.
 *
 * `kind` is `add` (a node dragged in from the menu or a drawer), `move` (a node
 * dragged to a new place) or `onto` (a card dropped onto the node `onto`).
 * `from` is where it starts: a palette's item, `{palette, item}`, or a node's
 * place, `{node, x, y}`. `node` is the type and label of what it drags, `ms`
 * how long the drag takes, and `id` names this one drag. The server sets both
 * fields as the drag starts and clears them as its drop ends, when its change
 * lands.
 *
 * Each tab starts the drag from its own page (`dragStart`):
 *
 * - a palette's item, named as `RAIL_PALETTES` names its palette, starts at its
 *   card in an open catalog drawer, else at its tile or row in the open
 *   palette, else at the rail's edge beside that palette's button;
 * - a node's place starts at the node, where this tab's canvas has it.
 *
 * Its cursor, in the agent's category tint with its name, carries a ghost of
 * what it drags from there to the drop point in `ms`: a copy of the tile, row or
 * card as it looks, else the node's outline. It holds the ghost by its top-left
 * corner, so the drop point is where the node's top-left lands, as for a node a
 * person drops. Under reduced motion it waits at the drop point instead. The
 * time is this tab's, from when the drag arrived: another machine's clock can be
 * off by minutes.
 */
import {
    PALETTE_ATTR,
    PALETTE_ITEM_ATTR,
    TOOLS_PALETTE_DROPDOWN_ATTR,
    railPaletteRootId,
} from "../../components/menus/nodes/toolsPaletteDismiss";
import { agentCategoryKey } from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";
import { MINIMIZED_NODE_HEIGHT, MINIMIZED_NODE_WIDTH } from "../../constants";
import { resolveNodeBoxSize } from "../../utils/nodeBoxSize";
import { CARRYING_FIELD, flowPointOf, pointerOf, type Point, type ViewTransform } from "./cursors";
import { colorOf, nameOf, type PresenceState } from "./presence";

/** How long a drag takes when its state does not say. */
export const DRAG_MS = 500;
/** The longest drag a state can ask for. */
const LONGEST_DRAG_MS = 10_000;

/** Marks the layer the drags are drawn in, whose ghosts are no drag's start. */
export const AGENT_DRAGS_ATTR = "data-agent-drags";

export type DragKind = "add" | "move" | "onto";
const KINDS: readonly string[] = ["add", "move", "onto"];

/** A palette's item: a node type, a dataset or group id, a model's package id. */
export interface PaletteItem {
    palette: string;
    item: string;
}

/** A node's place: the node, and its top-left in flow coordinates. Either can
 *  be missing, not both. */
export interface NodePlace {
    node: string | null;
    point: Point | null;
}

export interface Carrying {
    id: string;
    kind: DragKind;
    from: PaletteItem | NodePlace;
    /** The node a card is dropped onto (`kind` `onto`). */
    onto: string | null;
    /** What it drags, which its outline names. */
    node: { type: string; label: string };
    ms: number;
}

function finite(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

function word(value: unknown): string | null {
    return typeof value === "string" && value !== "" ? value : null;
}

export function isPaletteItem(from: Carrying["from"]): from is PaletteItem {
    return "palette" in from;
}

function fromOf(raw: unknown): Carrying["from"] | null {
    if (!raw || typeof raw !== "object") return null;
    const { palette, item, node, x, y } = raw as Record<string, unknown>;
    const name = word(palette);
    const id = word(item);
    if (name && id) return { palette: name, item: id };
    const place: NodePlace = { node: word(node), point: finite(x) && finite(y) ? { x, y } : null };
    return place.node || place.point ? place : null;
}

/** The drag a state holds, or null when it holds none, or nothing a drag can
 *  be: a state comes from another peer. */
export function carryingOf(state: PresenceState | null | undefined): Carrying | null {
    const raw = (state as { [CARRYING_FIELD]?: unknown } | null | undefined)?.[CARRYING_FIELD];
    if (!raw || typeof raw !== "object") return null;
    const { id, kind, from, onto, node, ms } = raw as Record<string, unknown>;
    const key = word(id) ?? (finite(id) ? String(id) : null);
    const start = fromOf(from);
    if (key === null || typeof kind !== "string" || !KINDS.includes(kind) || !start) return null;
    const dragged = (node && typeof node === "object" ? node : {}) as Record<string, unknown>;
    return {
        id: key,
        kind: kind as DragKind,
        from: start,
        onto: word(onto),
        node: { type: word(dragged.type) ?? "", label: word(dragged.label) ?? "" },
        ms: finite(ms) && ms >= 0 ? Math.min(ms, LONGEST_DRAG_MS) : DRAG_MS,
    };
}

/** The category tint of an agent: its badge's, through the same key. */
export function agentTint(category: string | null | undefined): string {
    return `var(--curio-category-agent-${agentCategoryKey(category)}-fg)`;
}

/** The color a drag is drawn in: its agent's category tint, or a person's own
 *  color for a state that names no agent. */
function dragColor(clientId: number, state: PresenceState): string {
    const agent = (state.user as { agent?: unknown } | undefined)?.agent;
    if (!agent || typeof agent !== "object") return colorOf(clientId, state);
    const category = (agent as { category?: unknown }).category;
    return agentTint(typeof category === "string" ? category : null);
}

// ── Where a drag starts ─────────────────────────────────────────────────────

/** What a drag carries: a copy of what it starts from, the size it has on the
 *  page, or the outline of its node, in flow units. */
export type DragGhost =
    | { kind: "copy"; element: HTMLElement; width: number; height: number }
    | { kind: "outline"; width: number; height: number; label: string };

export interface DragStart {
    /**
     * Where it starts. A point of the page (a card, a tile, the rail's edge)
     * stays where it is as the view moves; a point of the dataflow (a node's
     * place) moves with it. Null when this tab shows nothing to start from:
     * the drag then waits at its drop point.
     */
    at: (Point & { on: "page" | "dataflow" }) | null;
    /** What it starts from: `card`, `tile`, `rail`, `node`, or `drop` for none. */
    from: "card" | "tile" | "rail" | "node" | "drop";
    ghost: DragGhost;
}

/** What a drag's start reads of this tab. */
export interface StartPage {
    document: Document;
    /** The box this tab's canvas has of node *id*, in flow coordinates. */
    nodeBox(id: string): (Point & { width: number; height: number }) | null;
}

function clips(overflow: string): boolean {
    return overflow !== "" && overflow !== "visible";
}

/** Whether *element* is on the page to start from: drawn, not in a drawer that
 *  is closing, and not scrolled out of the list that holds it. */
function shown(element: HTMLElement): boolean {
    if (element.closest(`[aria-hidden="true"], [inert], [${AGENT_DRAGS_ATTR}]`)) return false;
    const box = element.getBoundingClientRect();
    if (!(box.width > 0 && box.height > 0)) return false;
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    const view = element.ownerDocument.defaultView;
    for (let up = element.parentElement; up && view; up = up.parentElement) {
        const style = view.getComputedStyle(up);
        if (!clips(style.overflowX) && !clips(style.overflowY)) continue;
        const frame = up.getBoundingClientRect();
        if (!(frame.width > 0 && frame.height > 0)) continue;
        if (x < frame.left || x > frame.right || y < frame.top || y > frame.bottom) return false;
    }
    return true;
}

/** The element that shows *from* on this tab's page, if one does: its card in
 *  an open drawer, which is in front of the rail, else its tile or row in an
 *  open palette. */
function shownItem(page: StartPage, from: PaletteItem): { element: HTMLElement; where: "card" | "tile" } | null {
    let tile: HTMLElement | null = null;
    for (const element of Array.from(page.document.querySelectorAll<HTMLElement>(`[${PALETTE_ITEM_ATTR}]`))) {
        if (element.getAttribute(PALETTE_ATTR) !== from.palette) continue;
        if (!(element.getAttribute(PALETTE_ITEM_ATTR) ?? "").split(/\s+/).includes(from.item)) continue;
        if (!shown(element)) continue;
        if (!element.closest(`[${TOOLS_PALETTE_DROPDOWN_ATTR}]`)) return { element, where: "card" };
        tile ??= element;
    }
    return tile ? { element: tile, where: "tile" } : null;
}

/** The rail's edge beside *palette*'s button: a closed palette's root is its
 *  button. */
function railEdge(page: StartPage, palette: string): Point | null {
    const root = page.document.getElementById(railPaletteRootId(palette));
    if (!root) return null;
    const box = root.getBoundingClientRect();
    if (!(box.width > 0 && box.height > 0)) return null;
    return { x: box.right, y: box.top + box.height / 2 };
}

function transparent(color: string): boolean {
    return color === "" || color === "transparent" || /^rgba\(.*,\s*0\)$/.test(color);
}

/** What a copy reads of the look *element* takes from where it is. */
const INHERITED = ["color", "font-family", "font-size", "font-weight", "line-height", "letter-spacing"];

/**
 * A copy of *element* as it looks on the page, for a ghost: its size, the
 * text style it inherits, and the background it is drawn on when it has none
 * of its own (a palette's tile is drawn on its panel). The copy names nothing,
 * so no selector, id lookup or tooltip finds it, and nothing in it takes the
 * focus or a click.
 */
export function ghostCopy(element: HTMLElement): HTMLElement {
    const copy = element.cloneNode(true) as HTMLElement;
    for (const part of [copy, ...Array.from(copy.querySelectorAll<HTMLElement>("*"))]) {
        for (const { name } of Array.from(part.attributes)) {
            if (
                name === "id" || name === "name" || name === "for" || name === "tabindex" || name === "draggable"
                || name === "href" || name === "title" || name === "role"
                || name.startsWith("data-") || name.startsWith("aria-")
            ) {
                part.removeAttribute(name);
            }
        }
    }
    copy.setAttribute("inert", "");
    const box = element.getBoundingClientRect();
    const view = element.ownerDocument.defaultView;
    if (view) {
        const style = view.getComputedStyle(element);
        for (const property of INHERITED) copy.style.setProperty(property, style.getPropertyValue(property));
        if (transparent(style.backgroundColor)) {
            for (let up = element.parentElement; up; up = up.parentElement) {
                const under = view.getComputedStyle(up).backgroundColor;
                if (!transparent(under)) {
                    copy.style.backgroundColor = under;
                    break;
                }
            }
        }
    }
    copy.style.boxSizing = "border-box";
    copy.style.margin = "0";
    copy.style.width = `${box.width}px`;
    copy.style.height = `${box.height}px`;
    return copy;
}

/** The outline's size for a drag with no node of this tab's to outline: the
 *  box the node it adds takes, or a node's chip for a card dropped onto one. */
function outlineSize(carrying: Carrying): { width: number; height: number } {
    if (carrying.kind === "onto") return { width: MINIMIZED_NODE_WIDTH, height: MINIMIZED_NODE_HEIGHT };
    return resolveNodeBoxSize({ type: carrying.node.type });
}

/** Where *carrying* starts on this tab's *page*, and what it carries. */
export function dragStart(carrying: Carrying, page: StartPage): DragStart {
    const label = carrying.node.label;
    const from = carrying.from;
    if (!isPaletteItem(from)) {
        const box = from.node ? page.nodeBox(from.node) : null;
        const at = box ?? from.point;
        // A node React Flow has not measured yet has no size of its own.
        const size = box && box.width > 0 && box.height > 0 ? box : outlineSize(carrying);
        return {
            at: at ? { x: at.x, y: at.y, on: "dataflow" } : null,
            from: at ? "node" : "drop",
            ghost: { kind: "outline", width: size.width, height: size.height, label },
        };
    }
    const shownFrom = shownItem(page, from);
    if (shownFrom) {
        const box = shownFrom.element.getBoundingClientRect();
        return {
            at: { x: box.left, y: box.top, on: "page" },
            from: shownFrom.where,
            ghost: { kind: "copy", element: ghostCopy(shownFrom.element), width: box.width, height: box.height },
        };
    }
    const ghost: DragGhost = { kind: "outline", ...outlineSize(carrying), label };
    const edge = railEdge(page, from.palette);
    return edge ? { at: { ...edge, on: "page" }, from: "rail", ghost } : { at: null, from: "drop", ghost };
}

// ── Playing it ──────────────────────────────────────────────────────────────

/** A drag as this tab plays it. */
export interface PlayedDrag {
    /** The peer's client and the drag's id. */
    key: string;
    clientId: number;
    carrying: Carrying;
    /** Its drop point, in flow coordinates. */
    drop: Point;
    name: string;
    color: string;
    /** When it arrived, by this tab's clock. */
    seenAt: number;
    start: DragStart;
    /** Under reduced motion: it waits at its drop point. */
    still: boolean;
}

/**
 * Every other peer's drag, from the states that carry one, each with its start
 * in this tab, read once, when it arrives.
 */
export class DragTracker {
    private readonly playing = new Map<string, PlayedDrag>();

    constructor(
        private readonly startOf: (carrying: Carrying) => DragStart,
        private readonly reducedMotion: () => boolean = () => false,
    ) {}

    /** The drags *others* hold at *now*, in client order. */
    read(others: ReadonlyArray<readonly [number, PresenceState]>, now: number): PlayedDrag[] {
        const drags: PlayedDrag[] = [];
        const held = new Set<string>();
        for (const [clientId, state] of others) {
            const carrying = carryingOf(state);
            const drop = pointerOf(state);
            if (!carrying || !drop) continue;
            const key = `${clientId}:${carrying.id}`;
            held.add(key);
            const known = this.playing.get(key);
            const drag: PlayedDrag = {
                key,
                clientId,
                carrying,
                drop: { x: drop.x, y: drop.y },
                name: nameOf(state),
                color: dragColor(clientId, state),
                seenAt: known ? known.seenAt : now,
                start: known ? known.start : this.startOf(carrying),
                still: known ? known.still : this.reducedMotion(),
            };
            this.playing.set(key, drag);
            drags.push(drag);
        }
        for (const key of Array.from(this.playing.keys())) {
            if (!held.has(key)) this.playing.delete(key);
        }
        return drags.sort((a, b) => a.clientId - b.clientId);
    }
}

/** When *drag*'s motion ends, by this tab's clock: null when it does not move. */
export function motionEndsAt(drag: PlayedDrag): number | null {
    return drag.still || !drag.start.at ? null : drag.seenAt + drag.carrying.ms;
}

/** Slow out of the start and into the drop, as a hand moves. */
function eased(done: number): number {
    return done < 0.5 ? 4 * done * done * done : 1 - (-2 * done + 2) ** 3 / 2;
}

/**
 * Where *drag*'s cursor is at *now*, in flow coordinates, on a canvas whose
 * top-left is at *origin* on the page and that shows *view*: on its way from
 * its start to its drop point, and at the drop point once its `ms` are over.
 */
export function dragPoint(drag: PlayedDrag, now: number, origin: Point, view: ViewTransform): Point {
    const at = drag.start.at;
    const ends = motionEndsAt(drag);
    if (!at || ends === null || now >= ends) return drag.drop;
    const start = at.on === "dataflow" ? at : flowPointOf(at, origin, view);
    const part = eased(Math.max(0, (now - drag.seenAt) / drag.carrying.ms));
    return { x: start.x + (drag.drop.x - start.x) * part, y: start.y + (drag.drop.y - start.y) * part };
}

/** Whether two lists of drags draw the same. */
export function sameDrags(a: readonly PlayedDrag[], b: readonly PlayedDrag[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((drag, i) => {
        const other = b[i];
        return drag.key === other.key && drag.drop.x === other.drop.x && drag.drop.y === other.drop.y
            && drag.name === other.name && drag.color === other.color;
    });
}
