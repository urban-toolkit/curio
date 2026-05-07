import React from "react";

declare const APP_VERSION: string;

const VersionBadge: React.FC = () => (
  <div style={{
    position: "fixed", bottom: 8, right: 12,
    fontSize: 11, color: "#666", pointerEvents: "none",
    userSelect: "none", zIndex: 9999,
    fontFamily: "monospace",
  }}>
    {APP_VERSION}
  </div>
);

export default VersionBadge;
