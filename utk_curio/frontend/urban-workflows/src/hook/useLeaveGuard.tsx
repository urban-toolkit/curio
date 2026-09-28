import React, { useCallback, useState } from "react";

import ConfirmDialog from "../components/ConfirmDialog";

export interface LeaveGuardCopy {
  title: string;
  body: string;
}

export const LEAVE_DATAFLOW: LeaveGuardCopy = {
  title: "Discard unsaved changes?",
  body: "Leaving this dataflow discards the changes you have not saved.",
};

export const LEAVE_DASHBOARD: LeaveGuardCopy = {
  title: "Discard unsaved layout?",
  body: "Leaving this dashboard discards the layout changes you have not saved.",
};

/**
 * Every way out of unsaved work asks the same question, in the same dialog.
 *
 * `beforeunload` covers a reload or a closed tab, never an in-app navigation,
 * so each in-app exit has to ask for itself. The top menu, the dashboard bar,
 * the dashboard's empty state, links inside a dataset's details and links in
 * agent chat all did or should have; this is the one implementation they share,
 * so none of them can skip the question or word it differently.
 *
 * `leave(action)` runs `action` at once when nothing is unsaved, and otherwise
 * holds it until the user confirms. Render `dialog` somewhere in the caller.
 */
export function useLeaveGuard(
  unsaved: boolean,
  copy: LeaveGuardCopy,
  options: { layer?: "default" | "overlay" } = {},
): {
  leave: (action: () => void, body?: string) => void;
  dialog: React.ReactNode;
} {
  const [pending, setPending] = useState<{ run: () => void; body: string } | null>(null);

  const leave = useCallback(
    (action: () => void, body?: string) => {
      if (!unsaved) {
        action();
        return;
      }
      setPending({ run: action, body: body ?? copy.body });
    },
    [unsaved, copy.body],
  );

  const dialog = pending ? (
    <ConfirmDialog
      title={copy.title}
      body={pending.body}
      confirmLabel="Discard and continue"
      cancelLabel="Stay here"
      destructive
      layer={options.layer}
      onConfirm={() => {
        const { run } = pending;
        setPending(null);
        run();
      }}
      onCancel={() => setPending(null)}
    />
  ) : null;

  return { leave, dialog };
}

export default useLeaveGuard;
