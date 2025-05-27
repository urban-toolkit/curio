import React from "react";
import { faGoogle } from "@fortawesome/free-brands-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import CSS from "csstype";
import { useGoogleLogin } from "@react-oauth/google";

import { useUserContext } from "../../providers/UserProvider";
import { useDialogContext } from "../../providers/DialogProvider";
import { UserTypeForm } from "./UserTypeForm";

export const GoogleButton = () => {
  const { googleSignIn, saveUserType } = useUserContext();
  const { setDialog, unsetDialog } = useDialogContext();

  const login = useGoogleLogin({
    onSuccess: async (codeResponse) => {
      const user = await googleSignIn(codeResponse.code);
      if (!user) return;

      unsetDialog();
      saveUserType("programmer");

      // Make the dialog for programmer or expert appear
      // if (user.type) unsetDialog();
      // else setDialog(<UserTypeForm />);
    },
    flow: "auth-code",
  });

  return (
    <button style={buttonStyle} onClick={login}>
      <FontAwesomeIcon style={{ marginRight: "5px" }} icon={faGoogle} /> Sign in
      with Google
    </button>
  );
};

const buttonStyle: CSS.Properties = {
  color: "#FFF",
  width: "400px",
  maxWidth: "95%",
  padding: "10px 0",
  borderRadius: "5px",
  border: "none",
  background: "#EA4C89",
  fontSize: "1.1em",
};
