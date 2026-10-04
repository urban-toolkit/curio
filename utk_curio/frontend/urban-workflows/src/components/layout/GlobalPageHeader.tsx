import React, { useMemo } from "react";
import clsx from "clsx";
import { Link, NavLink, useNavigate } from "react-router-dom";
import logo from "assets/curio-2.png";
import { useUserContext } from "../../providers/UserProvider";
import { useApiSettingsDrawerOptional } from "../../providers/ApiSettingsDrawerProvider";
import { useMonitorDrawerOptional } from "../../providers/MonitorDrawerProvider";
import { ApiSettingsRequestHost } from "../apiSettings/ApiSettingsRequestHost";
import { isStandaloneDashboard } from "../../standalone/dashboardPayload";
import styles from "./GlobalPageHeader.module.css";

export interface GlobalPageHeaderProps {
  /** The page's own controls, between the logo and the account. The canvas
   *  puts the dataflow's menus and the catalogs here, the dashboard its own
   *  actions; the section pages put nothing. */
  children?: React.ReactNode;
  /** Run `go` now, or after asking: the canvas and the dashboard guard their
   *  unsaved work behind the logo, as behind every other way out. */
  onLeave?: (go: () => void) => void;
  /** Extra classes on the bar, such as pinning it over the canvas. */
  className?: string;
}

/**
 * The top bar of every signed-in page: the section pages, the dataflow canvas
 * and the dashboard all render this one, so they cannot drift apart.
 *
 * Monitor and API Settings go to their pages from a section page. On the
 * canvas and the dashboard, which mount their drawers, they open those
 * instead, so the dataflow stays open.
 */
export function GlobalPageHeader({ children, onLeave, className }: GlobalPageHeaderProps) {
  const navigate = useNavigate();
  const settingsDrawer = useApiSettingsDrawerOptional();
  const monitorDrawer = useMonitorDrawerOptional();
  // A standalone dashboard is a document carrying its own data: there is no
  // server behind it to monitor, and no account whose keys could be set.
  const standalone = isStandaloneDashboard();

  return (
    <header
      className={clsx(styles.header, className)}
      // fitViewWithMenuOffset measures the canvas's bar by this (#493).
      data-curio-menu-bar="true"
    >
      <Link
        to="/projects"
        className={styles.logoLink}
        onClick={
          onLeave
            ? (event) => {
                event.preventDefault();
                onLeave(() => navigate("/projects"));
              }
            : undefined
        }
      >
        <img src={logo} alt="Curio" className={styles.logo} />
      </Link>
      {children && <div className={styles.slot}>{children}</div>}
      <div className={styles.right}>
        {!standalone && (
          <>
            {/* Unconditional: the monitor exists on every instance, not only a
                --deploy one, so there is no flag to read here. */}
            {monitorDrawer ? (
              <button className={styles.pill} type="button" onClick={monitorDrawer.openMonitor}>
                Monitor
              </button>
            ) : (
              <NavLink
                to="/monitor"
                end
                className={({ isActive }) => clsx(styles.pill, isActive && styles.pillCurrent)}
              >
                Monitor
              </NavLink>
            )}
            {/* The account's one credentials surface: every key it uses, and
                the model each agent runs on. */}
            {settingsDrawer ? (
              <button
                className={clsx(styles.pill, styles.apiSettings)}
                type="button"
                onClick={() => settingsDrawer.openApiSettings()}
              >
                API Settings
              </button>
            ) : (
              <NavLink
                to="/settings"
                className={({ isActive }) =>
                  clsx(styles.pill, styles.apiSettings, isActive && styles.pillCurrent)
                }
              >
                API Settings
              </NavLink>
            )}
          </>
        )}
        <AccountBlock />
      </div>
      {/* Opens API Settings on the place a card asks for, such as an agent's
          model from its details. The one host on any page, the canvas
          included: two would answer one request twice. */}
      {!standalone && <ApiSettingsRequestHost />}
    </header>
  );
}

/** The signed-in account: avatar, name and Sign out, or a way to sign in. */
function AccountBlock() {
  const { user, signout, enableUserAuth } = useUserContext();
  const navigate = useNavigate();

  const initials = useMemo(() => {
    const source = user?.name || user?.username || "";
    if (!source) return "?";
    return source
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }, [user?.name, user?.username]);

  if (!user) {
    return (
      <Link to="/auth/signin" className={styles.signIn} data-testid="login-link">
        Sign in
      </Link>
    );
  }

  const displayName = user.name || user.username || "User";

  return (
    <div className={styles.account} data-testid="user-menu">
      <div className={styles.avatar} aria-label="user avatar">
        {user.profile_image ? <img src={user.profile_image} alt={displayName} /> : initials}
      </div>
      <div className={styles.accountColumn}>
        <span className={styles.userName} title={displayName}>
          {displayName}
        </span>
        {enableUserAuth && (
          <button
            className={clsx(styles.pill, styles.signOut)}
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
  );
}

export default GlobalPageHeader;
