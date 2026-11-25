import React from "react";

import ConfirmDialog from "../../../ConfirmDialog";

/** The app's own dialog, not the browser's (#197): the last `window.confirm`
 * outside the top menu was unstyled, unthemed, and outside the modal stack.
 * It says what the agent stays attached to (`targetPhraseFor`'s `object`), and
 * it is asked on the overlay layer: the chat panel is above ModalShell's
 * default one, which put the dialog's right half, Clear included, under it. */
export const ClearConversationDialog: React.FC<{
  /** What the agent stays attached to: "the canvas", a node's name, or "the
   *  connection from A to B". */
  target: string;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({ target, onConfirm, onCancel }) => (
  <ConfirmDialog
    title="Clear this conversation?"
    body={`The transcript goes; the agent stays attached to ${target}.`}
    confirmLabel="Clear"
    cancelLabel="Keep it"
    destructive
    layer="overlay"
    onConfirm={onConfirm}
    onCancel={onCancel}
  />
);
