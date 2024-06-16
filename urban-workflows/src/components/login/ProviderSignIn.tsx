import React from "react";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faStar } from "@fortawesome/free-solid-svg-icons";
import { GoogleOAuthProvider } from "@react-oauth/google";

import { GoogleButton } from "./GoogleButton";

export const ProviderSignIn = () => {
  return (
    <GoogleOAuthProvider
      clientId={process.env.VITE_GOOGLE_OAUTH_CLIENT_ID || ""}
    >
      <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
        <h1 style={titleStyle}>
          Let's get started{" "}
          <FontAwesomeIcon style={{ color: "yellow" }} icon={faStar} />
        </h1>

        <p>Sign in to get access to the platform</p>

        <GoogleButton />
      </div>
    </GoogleOAuthProvider>
  );
};

const containerStyle: CSS.Properties = {
  width: "500px",
  maxWidth: "90%",
  height: "500px",
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
  alignItems: "center",
  backgroundColor: "white",
};

const titleStyle: CSS.Properties = {
  fontWeight: "bold",
  marginBottom: "20px",
};
