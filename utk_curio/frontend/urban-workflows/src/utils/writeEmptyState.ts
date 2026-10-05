/**
 * Write a grammar node's empty state into the element it draws into.
 *
 * A Vega view and an Autark map each own their container and fill it
 * imperatively, so there is no React subtree to put a component in; NodeEditor
 * renders either the output container or a `contentComponent`, never both.
 * Writing the copy here keeps it in the node body where it persists, which is
 * the point: its predecessor was a toast that vanished after a few seconds and
 * left an unexplained blank node behind (#224). And because nothing here is
 * React state, the editor's tabs are not disturbed while someone types.
 *
 * The copy comes from NODE_EMPTY_COPY, so it cannot drift from what Data Pool
 * and Simple View say for the shared states.
 */
// The same stylesheet NodeEmptyState uses, so a blank chart or map looks
// exactly like a blank Data Pool or Simple View rather than merely similar.
import emptyStyles from "../components/nodes/NodeEmptyState.module.css";
import { NODE_EMPTY_COPY, type NodeEmptyReason } from "./nodeEmptyState";

export function writeEmptyState(
  host: HTMLElement | null,
  reason: NodeEmptyReason | null,
  words: { title?: string; hint?: string | null } = {},
): void {
  if (!host || reason == null) return;

  const copy = NODE_EMPTY_COPY[reason];
  host.replaceChildren();
  host.setAttribute("data-curio-node-empty", reason);

  const wrapper = document.createElement("div");
  wrapper.className = emptyStyles.root;

  const title = document.createElement("span");
  title.className = emptyStyles.title;
  title.textContent = words.title ?? copy.title;
  wrapper.appendChild(title);

  const hint = document.createElement("span");
  hint.className = emptyStyles.hint;
  hint.textContent = words.hint ?? copy.hint;
  wrapper.appendChild(hint);

  host.appendChild(wrapper);
}

/** The node drew something: the marker would otherwise outlive the message. */
export function clearEmptyState(host: HTMLElement | null): void {
  host?.removeAttribute("data-curio-node-empty");
}
