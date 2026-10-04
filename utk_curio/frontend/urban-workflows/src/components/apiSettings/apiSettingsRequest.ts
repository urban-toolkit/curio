import type { AgentRemedy } from "../../services/agents";

/**
 * A card asks for one place in API Settings: "Add key for <host>" from the
 * Solve strip, the per-node Solve row and the review card, an agent's model
 * from its details, a source's key from the Discovery Catalog. API Settings is
 * mounted elsewhere, so a window event decouples them: the card REQUESTS a
 * place, and the one `ApiSettingsRequestHost` on the page opens the drawer on
 * it (canvas, dashboard) or goes to the settings page (every other page).
 */

/** The API keys tab's form for a key node code reads, host prefilled. */
export interface KeyFocus {
  section: "connection-keys";
  host?: string;
  suggestedName?: string;
}

/** The Agent configuration tab, scrolled to one agent's row. */
export interface AgentModelsFocus {
  section: "agent-models";
  agentId?: string;
}

/** The API keys tab, with one LLM configuration's editor open. */
export interface LlmConfigsFocus {
  section: "llm-configs";
  configId?: string;
}

/** The API keys tab, with one data source key's form open. */
export interface SourceKeyFocus {
  section: "source-key";
  slot?: string;
}

/** The place in API Settings a card asks for. */
export type ApiSettingsFocus = KeyFocus | AgentModelsFocus | LlmConfigsFocus | SourceKeyFocus;

/** The two tabs, as they appear in the settings page's path. */
export type ApiSettingsTab = "keys" | "agents";

const SECTIONS = new Set(["connection-keys", "agent-models", "llm-configs", "source-key"]);

export const API_SETTINGS_EVENT = "curio:api-settings";

function dispatch(focus: ApiSettingsFocus): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ApiSettingsFocus>(API_SETTINGS_EVENT, { detail: focus }));
}

export function requestConnectionKeys(focus: Omit<KeyFocus, "section">): void {
  dispatch({ section: "connection-keys", ...focus });
}

/** Open API Settings on the key a Discovery Catalog source sends. */
export function requestSourceKey(slot: string): void {
  dispatch({ section: "source-key", slot });
}

/** Open API Settings on the Agent configuration row of *agentId*. */
export function requestAgentModel(agentId?: string): void {
  dispatch({ section: "agent-models", agentId });
}

export function subscribeApiSettingsRequests(
  handler: (focus: ApiSettingsFocus) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<ApiSettingsFocus>).detail;
    if (detail && SECTIONS.has(detail.section)) handler(detail);
  };
  window.addEventListener(API_SETTINGS_EVENT, listener);
  return () => window.removeEventListener(API_SETTINGS_EVENT, listener);
}

/** The tab a focus opens on. */
export function tabForFocus(focus: ApiSettingsFocus | null): ApiSettingsTab {
  return focus?.section === "agent-models" ? "agents" : "keys";
}

/** The settings page's URL for a focus: the tab in the path, the rest in the
 *  query. `focusFromSearch` reads it back. */
export function settingsPath(focus: ApiSettingsFocus | null): string {
  const query = new URLSearchParams();
  if (focus?.section === "agent-models" && focus.agentId) query.set("agent", focus.agentId);
  if (focus?.section === "llm-configs" && focus.configId) query.set("config", focus.configId);
  if (focus?.section === "source-key" && focus.slot) query.set("service", focus.slot);
  if (focus?.section === "connection-keys") {
    query.set("add", "node");
    if (focus.host) query.set("host", focus.host);
    if (focus.suggestedName) query.set("name", focus.suggestedName);
  }
  const search = query.toString();
  return `/settings/${tabForFocus(focus)}${search ? `?${search}` : ""}`;
}

/** The focus a settings page URL carries, or null for a plain visit. */
export function focusFromSearch(tab: ApiSettingsTab, search: URLSearchParams): ApiSettingsFocus | null {
  if (tab === "agents") {
    const agentId = search.get("agent");
    return agentId ? { section: "agent-models", agentId } : null;
  }
  const configId = search.get("config");
  if (configId) return { section: "llm-configs", configId };
  const slot = search.get("service");
  if (slot) return { section: "source-key", slot };
  if (search.get("add") === "node") {
    return {
      section: "connection-keys",
      host: search.get("host") ?? undefined,
      suggestedName: search.get("name") ?? undefined,
    };
  }
  return null;
}

/** The bare hostname of a host-or-URL string: `https://api.census.gov/data?x=1` → `api.census.gov`. */
export function hostOf(hostOrUrl: string): string {
  const trimmed = (hostOrUrl ?? "").trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, "");
  let host = trimmed.split(/[/?#]/)[0] ?? "";
  if (host.includes("@")) host = host.slice(host.lastIndexOf("@") + 1);
  return host.replace(/:\d+$/, "").replace(/\.$/, "");
}

/** `api.census.gov` → `census`; `data.cityofchicago.org` → `cityofchicago`: the
 * second-level label, made name-safe (the backend's `suggest_name` twin). */
export function suggestName(hostOrUrl: string): string {
  const host = hostOf(hostOrUrl);
  const labels = host.split(".").filter(Boolean);
  const label = labels.length >= 2 ? labels[labels.length - 2] : labels[0] ?? "";
  return label.replace(/[^a-z0-9_-]/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

/** The focus a remedy asks for, or null when the remedy needs no form. */
export function remedyFocus(remedy: AgentRemedy | null | undefined): Omit<KeyFocus, "section"> | null {
  if (!remedy || remedy.kind !== "connection-key" || !remedy.host) return null;
  return { host: remedy.host, suggestedName: remedy.suggestedName };
}
