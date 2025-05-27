import React, { createContext, useCallback, useState } from "react";
import { GenericDialog } from "../components/GenericDialog";

interface DialogContextProps {
  setDialog: (dialog: React.ReactNode) => void;
  unsetDialog: () => void;
}
const DialogContext = createContext<DialogContextProps>({
  setDialog: () => {},
  unsetDialog: () => {},
});

const DialogProvider = ({ children }: { children: React.ReactNode }) => {
  const [dialog, setDialog] = useState<React.ReactNode | null>(null);

  const unsetDialog = useCallback(() => {
    setDialog(null);
  }, []);

  return (
    <DialogContext.Provider value={{ setDialog, unsetDialog }}>
      {children}
      {dialog && <GenericDialog dialog={dialog} />}
    </DialogContext.Provider>
  );
};

export const useDialogContext = () => {
  const context = React.useContext(DialogContext);
  if (!context) {
    throw new Error("useDialog must be used within a DialogProvider");
  }
  return context;
};

export default DialogProvider;
