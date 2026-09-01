import type { AgentCard } from "../../../api/agentsApi";
import { SortMode } from "../../packages/publishing/packageTypes";

/**
 * Free-text match for the Agent Catalog search bar ("Search agents, publishers,
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

/**
 * The add button's label.
 *
 * "Add to project" is the shared catalog wording - the same string the Node
 * and Data drawers use for the same per-dataflow write. This used to say
 * "Install", which `catalogCopy.test.tsx` bans outright because it described
 * neither scope: the drawer writes one dataflow's lockfile, while a browse
 * page writes the account.
 *
 * When the closure adds more than the row that was clicked, the count rides in
 * the label so the click is disclosed before it happens.
 */
export function installLabel(card: AgentCard): string {
  const missing = missingRequiredAgents(card);
  return missing.length
    ? `Add to project (+${missing.length} required)`
    : "Add to project";
}

/** The add button's title - names what else the click adds, or the dependency
 * that cannot be resolved (the server will refuse). */
export function installTitle(card: AgentCard): string | undefined {
  const missing = missingRequiredAgents(card);
  if (!missing.length) return undefined;
  const unresolvable = missing.filter((r) => !r.visible);
  if (unresolvable.length) {
    return `Cannot add: requires ${unresolvable.map((r) => r.id).join(", ")}, not available in the catalog or your imports`;
  }
  return `Also adds ${missing.map((r) => r.name).join(", ")} (required)`;
}
