import React from "react";
import CSS from "csstype";

interface Props {
  showGuest: boolean;
  onGuest: () => void;
}

export const AltAuthBox: React.FC<Props> = ({ showGuest, onGuest }) => {
  if (!showGuest) {
    return null;
  }

  return (
    <div style={containerStyle}>
      <div style={dividerStyle}>
        <span style={dividerLineStyle} />
        <span style={dividerTextStyle}>or</span>
        <span style={dividerLineStyle} />
      </div>

      <button type="button" style={guestBtnStyle} onClick={onGuest}>
        Continue as Guest
      </button>
    </div>
  );
};

const containerStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  marginTop: "16px",
};

const dividerStyle: CSS.Properties = {
  display: "flex",
  alignItems: "center",
  gap: "12px",
};

const dividerLineStyle: CSS.Properties = {
  flex: 1,
  height: "1px",
  backgroundColor: "#E0E0E0",
};

const dividerTextStyle: CSS.Properties = {
  fontSize: "13px",
  color: "#9E9E9E",
};

const guestBtnStyle: CSS.Properties = {
  width: "100%",
  padding: "10px",
  border: "1px solid #E0E0E0",
  borderRadius: "6px",
  backgroundColor: "#fff",
  fontSize: "14px",
  fontWeight: 500,
  cursor: "pointer",
  color: "#0F0F11",
};
