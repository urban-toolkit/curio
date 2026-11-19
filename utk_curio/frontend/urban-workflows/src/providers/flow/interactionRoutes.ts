/**
 * Where an interaction edge carries a selection (contracts/interactionEdges).
 *
 * An interaction edge carries selections both ways, so it is two routes: out
 * of the node at one end, into the node at the other. The handle at each end
 * says how much. A node's own handle (`in/out`) sends every view's selects,
 * and delivers to the whole node. A view's handle (`in/out@<id>`) sends that
 * view's selection alone (utils/autkSelects `selectsOfView`), and delivers to
 * that view alone, which the delivery names (`toView`), so the node lights it
 * there (adapters/node/autkGrammarBehavior). An edge saved before views had
 * dots joins two nodes' own handles, and carries what it always did.
 */
import { interactionHandleView, isInteractionEdge, type EdgeLike } from '../../contracts/interactionEdges';
import { selectsOfView } from '../../utils/autkSelects';
import type { IInteraction } from './flowTypes';

/** One way an interaction edge carries selections: out of a node, or one of its views, into a node, or one of its views. */
export type InteractionRoute = { from: string; fromView: string | null; to: string; toView: string | null };

type RoutedEdge = EdgeLike & { source?: unknown; target?: unknown };

/** The two routes of the interaction edge *edge*: source to target, and target to source. */
export function routesOfEdge(edge: RoutedEdge): [InteractionRoute, InteractionRoute] {
  const source = String(edge.source);
  const target = String(edge.target);
  const sourceView = interactionHandleView(edge.sourceHandle);
  const targetView = interactionHandleView(edge.targetHandle);
  return [
    { from: source, fromView: sourceView, to: target, toView: targetView },
    { from: target, fromView: targetView, to: source, toView: sourceView },
  ];
}

/** A key that is the same for two routes between the same ends and views. */
export function routeKey(route: InteractionRoute): string {
  return JSON.stringify([route.from, route.fromView, route.to, route.toView]);
}

/** Every route of the interaction edges among *edges*, each once, by its key, in the edges' order. */
export function interactionRoutes(edges: readonly RoutedEdge[]): Map<string, InteractionRoute> {
  const routes = new Map<string, InteractionRoute>();
  for (const edge of edges) {
    if (!isInteractionEdge(edge)) continue;
    for (const route of routesOfEdge(edge)) {
      const key = routeKey(route);
      if (!routes.has(key)) routes.set(key, route);
    }
  }
  return routes;
}

/** Whether two deliveries are the same: from one node, to one view (or the whole node), of the same selects. */
export function sameDelivery(a: unknown, b: unknown): boolean {
  const x = a as IInteraction | undefined;
  const y = b as IInteraction | undefined;
  if (!x || !y) return false;
  return x.nodeId === y.nodeId
    && (x.toView ?? null) === (y.toView ?? null)
    && JSON.stringify(x.details) === JSON.stringify(y.details);
}

/**
 * What the node *sender*'s selection *details* gives a node over *routes*,
 * each out of *sender* into that node: for each route, the selects it carries
 * (every one out of the sender's own handle, one view's out of that view's),
 * named with the view each came from and the view each goes to. Out of a
 * node's own handle the details go as they were sent, as before; out of a view
 * that sent no select, nothing. Two routes that give the same selects to the
 * same view give them once.
 */
export function deliveriesOver(sender: string, details: unknown, routes: readonly InteractionRoute[]): IInteraction[] {
  const out: IInteraction[] = [];
  for (const route of routes) {
    if (details === undefined || details === null) continue;
    const carried = route.fromView === null ? details : selectsOfView(details, route.fromView);
    if (route.fromView !== null && Object.keys(carried as object).length === 0) continue;
    const delivery: IInteraction = {
      nodeId: sender,
      details: carried,
      priority: 1,
      ...(route.fromView === null ? {} : { fromView: route.fromView }),
      ...(route.toView === null ? {} : { toView: route.toView }),
    };
    if (out.some((made) => sameDelivery(made, delivery))) continue;
    out.push(delivery);
  }
  return out;
}
