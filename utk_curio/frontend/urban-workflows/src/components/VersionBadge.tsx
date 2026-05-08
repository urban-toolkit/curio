import React, { useState, useEffect } from "react";

const VersionBadge: React.FC = () => {
  const [v, setV] = useState<string>("");
  useEffect(() => {
    fetch(process.env.BACKEND_URL + "/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setV(d.version))
      .catch(() => {});
  }, []);
  if (!v) return null;
  return (
    <div
      style={{
        position: "fixed",
        bottom: 8,
        right: 12,
        fontSize: 11,
        color: "#666",
        pointerEvents: "none",
        userSelect: "none",
        zIndex: 9999,
        fontFamily: "monospace",
      }}
    >
      {v}
    </div>
  );
};

export default VersionBadge;
