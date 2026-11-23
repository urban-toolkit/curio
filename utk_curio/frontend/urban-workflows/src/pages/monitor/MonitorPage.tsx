import React from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import logo from "assets/curio-2.png";

import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import { useUserContext } from "../../providers/UserProvider";
import MonitorContent from "./MonitorContent";
import { monitorPath, tabOfSegment } from "./monitorTabs";
import styles from "./MonitorPage.module.css";

/**
 * The deployment monitor: `/monitor` is its Status tab, `/monitor/usage` its
 * Usage tab, and any other path under it opens Status.
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
  const { tab: segment } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const tab = tabOfSegment(segment);

  if (tab === null) return <Navigate to="/monitor" replace />;

  return (
    <div className={styles.pageShell}>
      {user ? (
        <>
          <GlobalPageHeader>
            <AppSectionTabs />
          </GlobalPageHeader>
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
        <MonitorContent tab={tab} onTabChange={(next) => navigate(monitorPath(next))} />
      </div>

      <VersionBadge />
    </div>
  );
};

export default MonitorPage;
