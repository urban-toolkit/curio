import React, { useRef } from "react";
import clsx from "clsx";
import styles from "./ApiSettings.module.css";
import { useUserContext } from "../../providers/UserProvider";
import { AgentConfigTab } from "./AgentConfigTab";
import { ApiKeysTab } from "./ApiKeysTab";
import { useLlmListing } from "./useLlmListing";
import { useHostedGuest } from "./useHostedGuest";
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
  const { isSharedGuest } = useUserContext();
  const hostedGuest = useHostedGuest();
  const shared = !hostedGuest && (isSharedGuest || Boolean(llm.listing?.shared));
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const at = TABS.findIndex((t) => t.key === tab);
    const next = TABS[(at + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length].key;
    onTabChange(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className={styles.panel}>
      <div className={styles.tabs} role="tablist" aria-label="API Settings" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button
            key={t.key}
            ref={(el) => {
              tabRefs.current[t.key] = el;
            }}
            type="button"
            role="tab"
            id={`api-settings-tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={`api-settings-panel-${t.key}`}
            tabIndex={tab === t.key ? 0 : -1}
            className={clsx(styles.tab, tab === t.key && styles.tabActive)}
            onClick={() => onTabChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {shared ? (
        <p className={styles.sharedNote} role="note">
          Everyone using this Curio shares this account, so keys saved here are shared too.
        </p>
      ) : null}
      <div role="tabpanel" id={`api-settings-panel-${tab}`} aria-labelledby={`api-settings-tab-${tab}`}>
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
