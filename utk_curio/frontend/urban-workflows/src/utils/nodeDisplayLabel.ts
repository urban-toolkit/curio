/**
 * What a node is called: the name its canvas header shows (#775).
 *
 * `resolveNodeDisplayLabel` (palettePackageFactoryDraft.ts) calls this with the
 * label of the node's registered template. The name also titles the node's
 * computed dataset, whichever path saves it, so the backend names a node the
 * same way: `execution/node_names.py` is the twin, and both run
 * `nodeDisplayLabel.cases.json` beside this file.
 *
 * The node's renamed header, else its template's label, else its type in
 * words without the version. A purely numeric type is a node id rather than a
 * template: the renamed header names it, else the id itself.
 */

function asText(value: unknown): string {
  return value === null || value === undefined ? "" : String(value).trim();
}

function labelText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** A node type in words, without its package or version:
 *  `curio.builtin/data-loading@1` is "Data Loading". */
export function humanizeNodeType(nodeType: unknown): string {
  const text = asText(nodeType);
  const base = text.slice(text.lastIndexOf("/") + 1).replace(/@[0-9]+$/, "");
  return base
    .split(/[-_\s]+/)
    .filter((word) => word.length > 0)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

export function nodeDisplayLabel(
  nodeType: unknown,
  customLabel?: unknown,
  templateLabel?: unknown,
): string {
  const custom = labelText(customLabel);
  if (custom) return custom;
  const typeText = asText(nodeType);
  if (/^[0-9]+$/.test(typeText)) return typeText;
  return labelText(templateLabel) || humanizeNodeType(typeText);
}
