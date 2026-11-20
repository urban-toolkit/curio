import React from "react";
import styles from "./ApiSettings.module.css";
import { TabBar, tabPanelProps } from "../layout/TabBar";
import { useUserContext } from "../../providers/UserProvider";
import { AgentConfigTab } from "./AgentConfigTab";
import { ApiKeysTab } from "./ApiKeysTab";
import { useLlmListing } from "./useLlmListing";
import { isHostedGuest } from "./useHostedGuest";
import type { ApiSettingsFocus, ApiSettingsTab } from "./apiSettingsRequest";

const TABS: { key: ApiSettingsTab; label: string }[] = [
  { key: "keys", label: "API keys" },
  { key: "agents", label: "Agent configuration" },
];

/**
 * The account's API Settings, in two tabs: API keys (every key, one list) and
 * Agent configuration (which model each agent runs on). The settings page and
 * the canvas's drawer both render this, so the two cannot drift apart; the page
 * keeps the tab in its URL, the drawer in its state.
 */
export const ApiSettingsPanel: React.FC<{
  tab: ApiSettingsTab;
  onTabChange: (tab: ApiSettingsTab) => void;
  /** The place a card asked for: a key's form or an agent's row. */
  focus?: ApiSettingsFocus | null;
}> = ({ tab, onTabChange, focus = null }) => {
  const llm = useLlmListing();
  const { user, isSharedGuest, enableUserAuth } = useUserContext();
  const hostedGuest = isHostedGuest(user, enableUserAuth);
  const shared = !hostedGuest && (isSharedGuest || Boolean(llm.listing?.shared));

  return (
    <div className={styles.panel}>
      <TabBar tabs={TABS} selected={tab} onSelect={onTabChange} label="API Settings" idPrefix="api-settings" />
      {shared ? (
        <p className={styles.sharedNote} role="note">
          Everyone using this Curio shares this account, so keys saved here are shared too.
        </p>
      ) : null}
      <div {...tabPanelProps("api-settings", tab)}>
        {tab === "keys" ? (
          <ApiKeysTab llm={llm} hostedGuest={hostedGuest} focus={focus} />
        ) : (
          <AgentConfigTab llm={llm} focus={focus} onShowKeys={() => onTabChange("keys")} />
        )}
      </div>
    </div>
  );
};

export default ApiSettingsPanel;
