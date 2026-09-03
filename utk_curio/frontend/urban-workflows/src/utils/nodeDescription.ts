import type { NodeDescriptor } from "../registry/types";

/**
 * Does this node kind carry help text worth offering?
 *
 * A package manifest's ``description`` reaches the descriptor already
 * (``packagesClient.buildDescriptor``), and ``DescriptionModal`` has always been
 * able to render it. What was missing was a way to ASK for it: nothing on the
 * node opened the modal, so every kind's documentation was written, shipped and
 * unreachable (#225).
 *
 * Blank-but-present counts as absent. A manifest with ``"description": ""`` is a
 * kind whose author has not written the help yet, and an info button that opens
 * an empty panel is worse than no button.
 */
export function hasNodeDescription(desc: Pick<NodeDescriptor, "description"> | null | undefined): boolean {
  return typeof desc?.description === "string" && desc.description.trim().length > 0;
}

/**
 * The one-line form, for a tooltip or a palette row.
 *
 * Descriptions are written as prose and can run to a paragraph; the first
 * sentence is the part that fits somewhere small.
 */
export function nodeDescriptionSummary(
  desc: Pick<NodeDescriptor, "description"> | null | undefined,
): string {
  if (!hasNodeDescription(desc)) return "";
  const text = (desc as { description: string }).description.trim();
  const firstSentence = text.match(/^[^.!?]*[.!?]/);
  return (firstSentence ? firstSentence[0] : text).trim();
}
