import React from "react";
import { Link } from "react-router-dom";
import logo from "assets/curio-2.png";

import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import { useUserContext } from "../../providers/UserProvider";
import MonitorContent from "./MonitorContent";
import styles from "./MonitorPage.module.css";

/**
 * The deployment monitor.
 *
 * Public and unauthenticated, and present on every instance rather than only
 * under --deploy: the error log is as useful on a laptop as on a server.
 *
 * Because it is public, an anonymous visitor must not be shown the signed-in
 * chrome. GlobalPageHeader renders an avatar, a name and a Sign out button
 * whenever auth is enabled, which on a deployed instance is always, so this
 * page falls back to a logo-only bar when there is no user.
 */
export const MonitorPage: React.FC = () => {
  const { user } = useUserContext();

  return (
    <div className={styles.pageShell}>
      {user ? (
        <>
          <GlobalPageHeader />
          <AppSectionTabs />
        </>
      ) : (
        <header className={styles.publicBar}>
          <Link to="/" className={styles.publicBarLink}>
            <img src={logo} alt="Curio" className={styles.publicBarLogo} />
          </Link>
          <span className={styles.publicBarTitle}>Monitor</span>
        </header>
      )}

      <div className={styles.scroll}>
        <MonitorContent />
      </div>

      <VersionBadge />
    </div>
  );
};

export default MonitorPage;
