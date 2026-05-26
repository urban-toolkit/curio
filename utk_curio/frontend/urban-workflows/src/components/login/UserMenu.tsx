import React, { useMemo } from "react";
import CSS from "csstype";
import { Link, useNavigate } from "react-router-dom";

import { useUserContext } from "../../providers/UserProvider";

export const UserMenu = () => {
  const { user, signout, enableUserAuth } = useUserContext();
  const navigate = useNavigate();

  const initials = useMemo(() => {
    const source = user?.name || user?.username || "";
    if (!source) return "?";
    return source
      .split(/\s+/)
      .filter(Boolean)
      .map((p) => p[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }, [user?.name, user?.username]);

  if (!user) {
    return (
      <Link to="/auth/signin" style={loginStyle} data-testid="login-link">
        Login
      </Link>
    );
  }

  const handleSignOut = async () => {
    await signout();
    navigate("/auth/signin");
  };

  const displayName = user.name || user.username;

  return (
    <div style={containerStyle} className="nowheel nodrag" data-testid="user-menu">
      <div style={avatarStyle} aria-label="user avatar">
        {user.profile_image ? (
          <img
            src={user.profile_image}
            alt={displayName}
            style={avatarImgStyle}
          />
        ) : (
          <span style={avatarInitialsStyle}>{initials}</span>
        )}
      </div>
      
      <div style={infoColumnStyle}>
        <span style={nameStyle} title={displayName}>
          {displayName}
        </span>
        {enableUserAuth && (
          <button
            type="button"
            style={signoutBtnStyle}
            onClick={handleSignOut}
            data-testid="signout-button"
          >
            Sign out
          </button>
        )}
      </div>
    </div>
  );
};

const containerStyle: CSS.Properties = {
  marginLeft: "auto",
  display: "flex",
  alignItems: "center",
  gap: "8px",
  fontFamily: "Rubik, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif",
};

const infoColumnStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "2px",
};

const nameStyle: CSS.Properties = {
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
  overflow: "hidden",
  border: "1px solid #2A2A2E",
  flexShrink: 0,
};

const avatarImgStyle: CSS.Properties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

const avatarInitialsStyle: CSS.Properties = {
  fontSize: "11px",
  fontWeight: 700,
  letterSpacing: "0.3px",
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

const loginStyle: CSS.Properties = {
  marginLeft: "auto",
  border: "none",
  backgroundColor: "transparent",
  padding: "6px 10px",
  cursor: "pointer",
  borderRadius: "4px",
  fontWeight: "bold",
  color: "white",
  textDecoration: "none",
};
