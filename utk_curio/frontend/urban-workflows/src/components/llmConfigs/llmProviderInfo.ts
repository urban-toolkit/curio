import type { LlmConfig } from "../../api/llmConfigsApi";

/** A configuration editor's provider tab. */
export type UiMode = "openai" | "anthropic" | "gemini" | "custom" | "deployment";

export interface ProviderInfo {
  label: string;
  /** Only a placeholder: the suggestion shown when the Model box is empty. */
  model: string;
  keyLink: string;
  keyLinkLabel: string;
  showBaseUrl: boolean;
  baseUrlPlaceholder?: string;
  /** The provider's SDK needs a key. */
  keyRequired: boolean;
}

/**
 * The OpenAI preset's base URL, stored with the configuration. A blank URL
 * would fall through to whatever the server's environment points the OpenAI
 * SDK at, which on a custom deployment is another host.
 */
export const OPENAI_BASE_URL = "https://api.openai.com/v1";

// Ids are the canonical ones, without a date suffix: a constructed
// `-YYYYMMDD` variant is not guaranteed to resolve.
export const PROVIDER_INFO: Record<Exclude<UiMode, "deployment">, ProviderInfo> = {
  openai: {
    label: "OpenAI",
    model: "gpt-4o-mini",
    keyLink: "https://platform.openai.com/api-keys",
    keyLinkLabel: "Get your OpenAI key",
    showBaseUrl: false,
    keyRequired: false,
  },
  anthropic: {
    label: "Anthropic",
    model: "claude-haiku-4-5",
    keyLink: "https://console.anthropic.com/keys",
    keyLinkLabel: "Get your Anthropic key",
    showBaseUrl: false,
    keyRequired: true,
  },
  gemini: {
    label: "Gemini",
    model: "gemini-2.0-flash",
    keyLink: "https://aistudio.google.com/apikey",
    keyLinkLabel: "Get your Gemini key",
    showBaseUrl: false,
    keyRequired: true,
  },
  custom: {
    label: "Custom",
    model: "",
    keyLink: "",
    keyLinkLabel: "",
    showBaseUrl: true,
    baseUrlPlaceholder: "http://localhost:11434/v1  (Ollama, LM Studio, vLLM, …)",
    keyRequired: false,
  },
};

export const DEPLOYMENT_TAB_LABEL = "This Curio install";

/** The tab a stored configuration belongs on. */
export function uiModeOf(config: Pick<LlmConfig, "endpoint" | "apiType" | "baseUrl">): UiMode {
  if (config.endpoint === "deployment") return "deployment";
  if (config.apiType === "anthropic") return "anthropic";
  if (config.apiType === "gemini") return "gemini";
  if (config.apiType === "openai_compatible" && config.baseUrl.replace(/\/+$/, "") === OPENAI_BASE_URL) {
    return "openai";
  }
  return "custom";
}

/** The provider fields a save sends for *mode*. */
export function endpointFields(
  mode: UiMode,
  baseUrl: string,
  current?: Pick<LlmConfig, "apiType"> | null,
): { endpoint: "own" | "deployment"; apiType?: string; baseUrl?: string } {
  if (mode === "deployment") return { endpoint: "deployment" };
  if (mode === "anthropic" || mode === "gemini") return { endpoint: "own", apiType: mode, baseUrl: "" };
  if (mode === "openai") return { endpoint: "own", apiType: "openai_compatible", baseUrl: OPENAI_BASE_URL };
  // A Custom tab keeps a non-standard type it was created with (the scripted
  // provider in tests), and is otherwise any OpenAI-compatible server.
  const apiType = current?.apiType && current.apiType !== "anthropic" && current.apiType !== "gemini"
    ? current.apiType
    : "openai_compatible";
  return { endpoint: "own", apiType, baseUrl: baseUrl.trim() };
}

/** How the configurations table names a configuration's provider. */
export function providerLabel(config: Pick<LlmConfig, "endpoint" | "apiType" | "baseUrl">): string {
  const mode = uiModeOf(config);
  if (mode === "deployment") return DEPLOYMENT_TAB_LABEL;
  if (config.apiType === "testing") return "Scripted (tests)";
  return PROVIDER_INFO[mode].label;
}

/** " (on 3 Sep 2026)", or "" when the timestamp is missing or unparseable. */
export function formatSeenAt(iso?: string | null): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const shown = when.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  return " (on " + shown + ")";
}
