import type { AgentCard } from "../../../api/agentsApi";
import { SortMode } from "../../packages/publishing/packageTypes";

/**
 * Free-text match for the Agents Catalog search bar ("Search agents, hooks,
 * keywords..."): name, id, purpose, category, capabilities, hooks and
 * publisher, case-insensitive. Mirrors packageUtils.matchesSearch.
 */
export function matchesAgentSearch(card: AgentCard, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    card.name.toLowerCase().includes(q) ||
    card.id.toLowerCase().includes(q) ||
    card.purpose.toLowerCase().includes(q) ||
    card.category.toLowerCase().includes(q) ||
    card.capabilities.some((c) => c.toLowerCase().includes(q)) ||
    card.hooks.some((h) => h.toLowerCase().includes(q)) ||
    card.provenance.publisher.toLowerCase().includes(q)
  );
}

/**
 * Returns a sorted copy of the agent cards.
 * "name" sorts alphabetically (case-insensitive, same comparator as
 * sortPackages). "new" keeps the server-provided roster order — AgentCard
 * carries no creation timestamp, so the API list order is the recency truth.
 */
export function sortAgentCards(cards: AgentCard[], mode: SortMode): AgentCard[] {
  const next = [...cards];
  if (mode === "name") {
    next.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }
  return next;
}
