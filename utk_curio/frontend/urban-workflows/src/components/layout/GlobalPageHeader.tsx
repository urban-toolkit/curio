import React from "react";
import CSS from "csstype";
import { Link, useNavigate } from "react-router-dom";
import logo from "assets/curio-2.png";
import { useUserContext } from "../../providers/UserProvider";

export function GlobalPageHeader() {
  const { user, signout, enableUserAuth } = useUserContext();
  const navigate = useNavigate();

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
        <button style={navBtnStyle} type="button" onClick={() => navigate("/projects")}>
          Projects
        </button>
        <div style={avatarStyle}>{initials}</div>
        <div style={userInfoColumnStyle}>
          <span style={userNameStyle}>{user?.name || "User"}</span>
          {enableUserAuth && (
            <button
              style={signoutBtnStyle}
              type="button"
              onClick={async () => {
                await signout();
                navigate("/auth/signin");
              }}
            >
              Logout
            </button>
          )}
        </div>
      </div>
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

const navBtnStyle: CSS.Properties = {
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
