/**
 * The marks the first paragraph of a function's docstring, or a line of the
 * page that lists Curio's functions, sets words with: reST's ``literal``, a
 * role's :func:`name` and Markdown's `code` as code, **strong**, and *emphasis*,
 * over the pattern in docMarkup.json, which the backend reads too
 * (function_nodes.plain_doc, for the description of a node made from a
 * function). docMarkup.cases.json holds the cases both sides run.
 */
import docMarkup from "./docMarkup.json";

/** What a part of a text is: words no mark sets, or the words one sets. */
export type DocPartKind = "text" | "code" | "strong" | "emphasis";

export interface DocPart {
  kind: DocPartKind;
  text: string;
}

/** The kind of mark each group of the pattern holds the words of, in group order. */
const GROUP_KINDS = docMarkup.groups as DocPartKind[];

/** *doc* in order: each mark's words, without the mark, and the words between. */
export function docParts(doc: string): DocPart[] {
  const marks = new RegExp(docMarkup.pattern, "g");
  const parts: DocPart[] = [];
  let at = 0;
  for (let match = marks.exec(doc); match !== null; match = marks.exec(doc)) {
    if (match.index > at) parts.push({ kind: "text", text: doc.slice(at, match.index) });
    const group = match.findIndex((words, i) => i > 0 && words !== undefined);
    parts.push({ kind: GROUP_KINDS[group - 1], text: match[group] });
    at = match.index + match[0].length;
  }
  if (at < doc.length) parts.push({ kind: "text", text: doc.slice(at) });
  return parts;
}

/** *doc* without its marks: the words alone, as a text tooltip shows them. */
export function plainDoc(doc: string): string {
  return docParts(doc)
    .map((part) => part.text)
    .join("");
}
