import React from "react";

import ConfirmDialog from "../../../ConfirmDialog";

/** The app's own dialog, not the browser's (#197): the last `window.confirm`
 * outside the top menu was unstyled, unthemed, and outside the modal stack. */
export const ClearConversationDialog: React.FC<{ onConfirm: () => void; onCancel: () => void }> = ({
  onConfirm,
  onCancel,
}) => (
  <ConfirmDialog
    title="Clear this conversation?"
    body="The transcript goes; the agent stays attached to this node."
    confirmLabel="Clear"
    cancelLabel="Keep it"
    destructive
    onConfirm={onConfirm}
    onCancel={onCancel}
  />
);
