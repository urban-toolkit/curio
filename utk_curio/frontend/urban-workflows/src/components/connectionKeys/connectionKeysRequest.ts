import type { AgentRemedy } from "../../services/agents";

/**
 * dev/116: "Add key for <host>" is offered from three cards (the Solve strip,
 * the per-node Solve row, the review card's attempt trail) and the settings
 * modal is mounted elsewhere. A window event decouples them: a card REQUESTS
 * an API Settings section; whichever host component is mounted
 * (`ConnectionKeysModalHost`) opens the modal on it.
 */
export interface KeyFocus {
  section: "connection-keys";
  host?: string;
  suggestedName?: string;
}

/** The Agent models section, scrolled to one agent's row. */
export interface AgentModelsFocus {
  section: "agent-models";
  agentId?: string;
}

/** The LLM configurations section, with one configuration's editor open. */
export interface LlmConfigsFocus {
  section: "llm-configs";
  configId?: string;
}

/** The Discovery Catalog section, scrolled to one key slot's row. */
export interface SourceKeyFocus {
  section: "source-key";
  slot?: string;
}

/** The API Settings section a card asks for. */
export type ConnectionKeysFocus = KeyFocus | AgentModelsFocus | LlmConfigsFocus | SourceKeyFocus;

const SECTIONS = new Set(["connection-keys", "agent-models", "llm-configs", "source-key"]);

export const CONNECTION_KEYS_EVENT = "curio:connection-keys";

function dispatch(focus: ConnectionKeysFocus): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ConnectionKeysFocus>(CONNECTION_KEYS_EVENT, { detail: focus }));
}

export function requestConnectionKeys(focus: Omit<KeyFocus, "section">): void {
  dispatch({ section: "connection-keys", ...focus });
}

/** Open API Settings on the key a Discovery Catalog source sends. */
export function requestSourceKey(slot: string): void {
  dispatch({ section: "source-key", slot });
}

/** Open API Settings on the Agent models row of *agentId*. */
export function requestAgentModel(agentId?: string): void {
  dispatch({ section: "agent-models", agentId });
}

export function subscribeConnectionKeysRequests(
  handler: (focus: ConnectionKeysFocus) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<ConnectionKeysFocus>).detail;
    if (detail && SECTIONS.has(detail.section)) handler(detail);
  };
  window.addEventListener(CONNECTION_KEYS_EVENT, listener);
  return () => window.removeEventListener(CONNECTION_KEYS_EVENT, listener);
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
