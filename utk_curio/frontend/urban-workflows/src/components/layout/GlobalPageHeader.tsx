import React, { useState } from "react";
import CSS from "csstype";
import { Link, NavLink, useNavigate } from "react-router-dom";
import logo from "assets/curio-2.png";
import { useUserContext } from "../../providers/UserProvider";
import ApiSettingsModal from "../ApiSettingsModal";
import { ConnectionKeysModalHost } from "../connectionKeys/ConnectionKeysModalHost";

export function GlobalPageHeader() {
  const { user, signout, enableUserAuth } = useUserContext();
  const navigate = useNavigate();
  const [apiSettingsOpen, setApiSettingsOpen] = useState(false);

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "?";

  return (
    <header style={topBarStyle}>
      <Link to="/projects" style={logoLinkStyle}>
        <img src={logo} alt="Curio" style={logoImgStyle} />
      </Link>
      <div style={topBarRightStyle}>
        {/* Unconditional: the monitor exists on every instance, not only a
            --deploy one, so there is no flag to read here. */}
        <NavLink
          to="/monitor"
          end
          style={({ isActive }) => (isActive ? monitorLinkActiveStyle : monitorLinkStyle)}
        >
          Monitor
        </NavLink>
        {/* The account's one credentials surface: its LLM configurations,
            the HuggingFace token, and the data-portal tokens the Discovery Catalog
            Catalog uses. The name has lagged the contents twice now (it was "LLM
            Settings" before the HuggingFace token); renaming it reaches about
            a hundred references, so it is worth its own change rather than a
            feature's. */}
        <button style={apiSettingsBtnStyle} type="button" onClick={() => setApiSettingsOpen(true)}>
          API Settings
        </button>
        <div style={avatarStyle}>{initials}</div>
        <div style={userInfoColumnStyle}>
          <span style={userNameStyle}>{user?.name || "User"}</span>
          {enableUserAuth && (
            <button
              style={signoutBtnStyle}
              type="button"
              data-testid="signout-button"
              onClick={async () => {
                await signout();
                navigate("/auth/signin");
              }}
            >
              Sign out
            </button>
          )}
        </div>
      </div>
      <ApiSettingsModal isOpen={apiSettingsOpen} onClose={() => setApiSettingsOpen(false)} />
      {/* Opens API Settings on the section a card asks for, such as an agent's
          model from its details. The canvas mounts its own. */}
      <ConnectionKeysModalHost />
    </header>
  );
}

const topBarStyle: CSS.Properties = {
  height: "65px",
  backgroundColor: "#1E1F23",
  display: "flex",
  alignItems: "center",
  padding: "10px 20px 10px 10px",
  justifyContent: "space-between",
  borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
  flexShrink: 0,
};

const logoLinkStyle: CSS.Properties = { display: "contents" };

const logoImgStyle: CSS.Properties = {
  maxHeight: "100%",
  width: "auto",
  marginLeft: "15px",
  marginRight: "15px",
  cursor: "pointer",
};

const topBarRightStyle: CSS.Properties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
};

const apiSettingsBtnStyle: CSS.Properties = {
  background: "none",
  border: "1px solid #444",
  borderRadius: "4px",
  color: "#ddd",
  fontSize: "12px",
  fontWeight: 500,
  padding: "5px 12px",
  cursor: "pointer",
  marginRight: "12px",
};

// API Settings' pill as a link; the row's gap spaces the two.
const monitorLinkStyle: CSS.Properties = {
  ...apiSettingsBtnStyle,
  marginRight: 0,
  textDecoration: "none",
};

const monitorLinkActiveStyle: CSS.Properties = {
  ...monitorLinkStyle,
  borderColor: "#ddd",
  color: "#fff",
};

const userInfoColumnStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "2px",
};

const userNameStyle: CSS.Properties = {
  color: "#fff",
  fontSize: "12px",
  fontWeight: 500,
  maxWidth: "110px",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const avatarStyle: CSS.Properties = {
  width: "28px",
  height: "28px",
  borderRadius: "50%",
  backgroundColor: "#fff",
  color: "#0F0F11",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: "11px",
  fontWeight: 700,
  border: "1px solid #2A2A2E",
  flexShrink: 0,
};

const signoutBtnStyle: CSS.Properties = {
  background: "none",
  border: "1px solid #444",
  borderRadius: "4px",
  color: "#ddd",
  fontSize: "11px",
  fontWeight: 500,
  padding: "3px 10px",
  cursor: "pointer",
  lineHeight: 1.3,
};
