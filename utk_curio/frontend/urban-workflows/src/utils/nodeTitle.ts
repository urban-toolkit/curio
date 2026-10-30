/**
 * A node's one name, ``data.title`` (Trill ``title``): what its header shows,
 * what a rename sets and what an agent names it. A node starts with its
 * template's label; a note starts with none, since its title is its heading.
 * A dataflow saved before ``title`` was the one name holds a renamed header at
 * ``metadata.packageTemplateLabel`` (or ``data.packageTemplateLabel``), which
 * wins over a ``title`` beside it; ``saved_node_title`` in
 * ``backend/app/execution/node_names.py`` reads it the same way.
 */
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import type { NodeTemplateId } from "../registry/types";

const NOTE_TYPE = /^curio\.builtin\/note(@[0-9]+)?$/;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function isNoteType(nodeType: unknown): boolean {
  return typeof nodeType === "string" && NOTE_TYPE.test(nodeType);
}

/** The title a new node gets: *title* when given, else its template's label
 *  (none for a note, or a template the registry does not know yet). */
export function initialNodeTitle(nodeType: string, title?: unknown): string | undefined {
  const given = text(title);
  if (given) return given;
  if (isNoteType(nodeType)) return undefined;
  let label = "";
  try {
    label = text(tryGetNodeDescriptor(nodeType as NodeTemplateId)?.label);
  } catch {
    label = "";
  }
  return label || undefined;
}

/** The title a saved node holds: the renamed header of an older save first,
 *  then its ``title``; "" when it has neither. */
export function savedNodeTitle(node: {
  title?: unknown;
  metadata?: { packageTemplateLabel?: unknown } | null;
  data?: { packageTemplateLabel?: unknown } | null;
}): string {
  return text(node.metadata?.packageTemplateLabel) || text(node.data?.packageTemplateLabel) || text(node.title);
}
