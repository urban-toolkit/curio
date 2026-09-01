import React from "react";
import ModalShell from "./ModalShell";
import { useDialogContext } from "../providers/DialogProvider";

export function GenericDialog({ dialog }: { dialog: React.ReactNode }) {
  const { unsetDialog } = useDialogContext();
  return (
    <ModalShell onClose={unsetDialog} label="Dialog">
      {dialog}
    </ModalShell>
  );
}
