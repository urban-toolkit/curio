/**
 * Catalog-scope shapes: definition cards, requirements, install results, facets, and the deployment provider default.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

/** One agent card as returned by the backend (camelCase). */
export interface AgentCard {
  id: string; // e.g. "agent.my-helper"
  version: string;
  dirName: string; // "<id>@<version>"
  name: string;
  category: string; // data | node | canvas | package | evaluate
  purpose: string;
  capabilities: string[];
  hooks: string[]; // compatible target kinds: node | canvas | connection
  provenance: { publisher: string; trust: string | null };
  imported: boolean;
  installedInProject: boolean;
  published: boolean;
  /** Eligible for Publish: an owned, store-backed definition (not a built-in). */
  publishable: boolean;
  /** Which list this card came from. Same vocabulary as the drawer's tabs
   *  (AgentScope) - one set of words for one idea. */
  scope: "browse" | "imports" | "installed";
  /** dev/106: server-resolved hard dependencies (``requiresAgents``) — what an
   * Install adds alongside this agent. ``[]`` for every leaf agent. */
  requiresAgents: AgentRequirement[];
  /** Whether the agent is a catalog card. Every listing shows cards only; an
   * internal built-in runs as a delegate and is never listed or attached. */
  inCatalog?: boolean;
}

/** An agent, and optionally one of its capabilities, that reads a catalog
 * setting. A null capability means every run of the agent. */
export interface CatalogSettingReader {
  agentId: string;
  agentName: string;
  capability: string | null;
  /** An internal agent: it runs only as a delegate, never as a card. */
  internal: boolean;
}

/** One catalog setting: a value the user owns, such as the keyword types. */
export interface CatalogSetting {
  key: string;
  label: string;
  description: string;
  /** JSON Schema of the value. */
  schema: Record<string, unknown>;
  default: unknown;
  value: unknown;
  isDefault: boolean;
  readBy: CatalogSettingReader[];
}

export interface CatalogSettingsResponse {
  settings: CatalogSetting[];
  /** False for an account that may not change them, with the reason. */
  editable: boolean;
  reason: string | null;
}

/** One direct hard dependency of an agent (dev/106). */
export interface AgentRequirement {
  id: string;
  name: string;
  /** The visible coordinate an install would add; null when visible nowhere. */
  coord: string | null;
  visible: boolean;
  installedInProject: boolean;
}

/** dev/106: the install response — the lockfile plus what this call added. */
export interface AgentInstallResponse {
  agents: string[];
  /** Coords newly added by this call, root first (empty on an idempotent re-install). */
  installed: string[];
  /** The root's required closure (installed or not). */
  required: string[];
}

/** Facet counts, keyed by facet then by value. Every key is present at zero,
 *  so a rail renders a complete set of rows rather than only the populated
 *  ones - the same contract `GET /api/datasets/catalog` returns. */
export interface AgentCatalogFacets {
  category: Record<string, number>;
  origin: Record<string, number>;
}

export interface AgentListResponse {
  /** The rows. `agents` is the historical name and still returned; `items`
   *  matches the other catalogs and is what new surfaces should read. */
  agents: AgentCard[];
  items?: AgentCard[];
  /** Present on `/catalog` only; the scoped lists have nothing to facet. */
  facets?: AgentCatalogFacets;
}
