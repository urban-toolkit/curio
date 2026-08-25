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

/** dev/106: the hard dependencies an Install of *card* would add — those not
 * yet in the project. Tolerates payloads that predate the field. */
export function missingRequiredAgents(card: AgentCard): AgentCard["requiresAgents"] {
  return (card.requiresAgents ?? []).filter((r) => !r.installedInProject);
}

/** dev/106: the Install button's label — "Install" when the closure is
 * satisfied, "Install +N required" when the click adds N more agents. */
export function installLabel(card: AgentCard): string {
  const missing = missingRequiredAgents(card);
  return missing.length ? `Install +${missing.length} required` : "Install";
}

/** dev/106: the Install button's title — names what the click adds, or the
 * dependency that cannot be resolved (the server will refuse). */
export function installTitle(card: AgentCard): string | undefined {
  const missing = missingRequiredAgents(card);
  if (!missing.length) return undefined;
  const unresolvable = missing.filter((r) => !r.visible);
  if (unresolvable.length) {
    return `Cannot install: requires ${unresolvable.map((r) => r.id).join(", ")}, not available in the catalog or your imports`;
  }
  return `Also installs ${missing.map((r) => r.name).join(", ")} (required)`;
}
