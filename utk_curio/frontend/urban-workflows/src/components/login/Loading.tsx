import React from "react";
import CSS from "csstype";
import Spinner from "react-bootstrap/Spinner";

export const Loading = () => {
  return (
    <div style={containerStyle}>
      <Spinner animation="border" variant="primary" />
    </div>
  );
};

const containerStyle: CSS.Properties = {
  position: "fixed",
  top: 0,
  bottom: 0,
  right: 0,
  left: 0,
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
  alignItems: "center",
  backgroundColor: "rgba(0,0,0,.3)",
};
