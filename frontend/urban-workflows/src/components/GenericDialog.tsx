import React from "react";
import { useDialogContext } from "../providers/DialogProvider";

export function GenericDialog({ dialog }: { dialog: React.ReactNode }) {
  const { unsetDialog } = useDialogContext();
  return (
    <div style={containerStyle} onClick={unsetDialog}>
      {dialog}
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  position: "fixed",
  top: "0",
  left: "0",
  width: "100%",
  height: "100%",
  backgroundColor: "rgba(0, 0, 0, 0.5)",
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
};
