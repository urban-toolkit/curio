/**
 * What a failed run says, for a node body that shows it in a line of its own
 * (the Map Edits node's): a Python traceback's last line without its
 * exception's name, where a node's own refusals end, else the message as it is.
 */
export function failureLine(content: unknown): string {
  const text = String(content ?? "").trim();
  if (!text.includes("Traceback (most recent call last)")) return text;
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const last = lines[lines.length - 1] ?? text;
  return last.replace(/^[A-Za-z_][\w.]*(Error|Exception): /, "");
}
