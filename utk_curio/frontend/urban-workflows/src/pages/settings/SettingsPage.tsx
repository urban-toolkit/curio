import React, { useMemo } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import { ApiSettingsPanel } from "../../components/apiSettings/ApiSettingsPanel";
import { focusFromSearch, type ApiSettingsTab } from "../../components/apiSettings/apiSettingsRequest";
import shellStyles from "../monitor/MonitorPage.module.css";
import styles from "./SettingsPage.module.css";

const TABS = new Set<string>(["keys", "agents"]);

/**
 * API Settings as a page: `/settings/keys` and `/settings/agents`, with the
 * place a card asked for in the query (`settingsPath`). The section pages' top
 * bar links here; the canvas and the dashboard open the same panel in a drawer.
 */
export const SettingsPage: React.FC = () => {
  const { tab } = useParams<{ tab?: string }>();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const known = tab !== undefined && TABS.has(tab);
  const focus = useMemo(
    () => (known ? focusFromSearch(tab as ApiSettingsTab, search) : null),
    [known, tab, search],
  );

  if (!known) return <Navigate to="/settings/keys" replace />;

  return (
    <div className={shellStyles.pageShell}>
      <GlobalPageHeader />
      <AppSectionTabs />
      <div className={shellStyles.scroll}>
        <main className={styles.page}>
          <h1 className={styles.title}>API Settings</h1>
          <ApiSettingsPanel
            tab={tab as ApiSettingsTab}
            onTabChange={(next) => navigate(`/settings/${next}`)}
            focus={focus}
          />
        </main>
      </div>
      <VersionBadge />
    </div>
  );
};

export default SettingsPage;
