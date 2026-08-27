import type { AgentAttachment } from "../../../api/agentsApi";

/** Longest accepted conversation title — mirrors the backend cap (memo dev/25). */
export const TITLE_MAX_CHARS = 40;

/**
 * "<Template Name>: <Custom Title>" when the instance has a conversation
 * title, else the plain template name (memo dev/25). The single composition
 * point for every surface that identifies an attached instance (dock tooltip,
 * badge labels, chat header); the prefix is the template's name and is never
 * stored or edited.
 */
export function attachmentDisplayName(
  attachment: Pick<AgentAttachment, "name" | "title">,
): string {
  return attachment.title ? `${attachment.name}: ${attachment.title}` : attachment.name;
}
