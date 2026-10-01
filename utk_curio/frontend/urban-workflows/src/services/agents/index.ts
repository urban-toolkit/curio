/**
 * The agents service layer (memo dev/142, F1) — the twin of `services/datasetCatalog`.
 *
 * Transport (`agentsApi`, `agentStream`), the window events and drag helpers,
 * the hooks over the transport (`useAgentCatalog`, as `datasetCatalogHooks`
 * is to the datasets layer), the pure logic the surfaces share, and every type
 * by concern. Components render; this layer owns transport, the hooks over it
 * and pure logic.
 */

export * from "./types";
export * from "./agentsApi";
export * from "./agentStream";
export * from "./agentEvents";
export * from "./agentDrag";
export * from "./useAgentCatalog";
export * from "./useAgentAttachments";
export * from "./agentRunStatus";
export * from "./agentRunContext";
export * from "./attachmentDisplayName";
export * from "./builderTemplates";
export * from "./agentListUtils";
export * from "./buildUploadPayload";
export * from "./sanitizeAgentContent";
