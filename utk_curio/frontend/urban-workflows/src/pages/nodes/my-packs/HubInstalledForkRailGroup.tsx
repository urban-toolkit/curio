import React, { useCallback, useEffect, useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../../api/packsApi";
import { CatalogPublishPill } from "../../../components/packs/CatalogPublishPill";
import { ForkFamilyPicker } from "../../../components/packs/ForkFamilyPicker";
import {
  FORK_SELECTION_SESSION_PREFIX,
  ForkFamilyGroup,
  formatForkOfSubtitle,
  resolveForkFamilySelectionKey,
} from "../../../utils/forkPackLineage";
import { MyPackIconActions } from "./MyPackIconActions";
import { MyPacksCallbacks } from "./myPacksTypes";
import styles from "./MyPacks.module.css";

export interface HubInstalledForkRailGroupProps extends MyPacksCallbacks {
  family: ForkFamilyGroup<PackPayload>;
  manualForkDirByRoot: Record<string, string>;
  setManualForkDirByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  busy: boolean;
  paletteDockBusy: string | null;
  catalogPublishedDirs: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
}

/**
 * Renders a fork-family group in the My Packs sidebar.
 * Shows a family title, a ForkFamilyPicker select, and a list-item row
 * for each fork member — the selected member is highlighted.
 */
export const HubInstalledForkRailGroup = React.memo(function HubInstalledForkRailGroup({
  family,
  manualForkDirByRoot,
  setManualForkDirByRoot,
  busy,
  paletteDockBusy,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackKey,
  onExport,
  onUninstall,
  onPaletteDockToggle,
  onPublishToCatalog,
  onOpenForkInFactory,
}: HubInstalledForkRailGroupProps) {
  const manualPick = manualForkDirByRoot[family.rootKey];

  const resolverMembers = useMemo(
    () => family.members.map((m) => ({ key: m.dirName })),
    [family.members],
  );

  const resolvedDir = useMemo(
    () => resolveForkFamilySelectionKey(family.rootKey, resolverMembers, "", manualPick),
    [family.rootKey, resolverMembers, manualPick],
  );

  useEffect(() => {
    try {
      sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + family.rootKey, resolvedDir);
    } catch {
      /* noop */
    }
  }, [family.rootKey, resolvedDir]);

  const selectedPack = useMemo(
    () => family.members.find((p) => p.dirName === resolvedDir) ?? family.members[0]!,
    [family.members, resolvedDir],
  );

  const forkPickerOptions = useMemo(
    () =>
      family.members.map((m) => ({
        key: m.dirName,
        label: `${m.name} (${m.packId} · v${m.version})`,
      })),
    [family.members],
  );

  const onForkPicked = useCallback(
    (next: string) => {
      setManualForkDirByRoot((prev) => ({ ...prev, [family.rootKey]: next }));
      try {
        sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + family.rootKey, next);
      } catch {
        /* noop */
      }
    },
    [family.rootKey, setManualForkDirByRoot],
  );

  return (
    <section
      className={styles.hubForkFamily}
      aria-labelledby={`fork-rail-head-${family.rootKey}`}
    >
      <div className={styles.hubForkFamilyToolbar}>
        <div>
          <div
            id={`fork-rail-head-${family.rootKey}`}
            className={styles.hubForkRailTitleRow}
          >
            <button
              type="button"
              className={styles.hubPackFactoryTitleBtn}
              title="Fork in Node Factory (new install; source unchanged)"
              onClick={() => onOpenForkInFactory(selectedPack)}
            >
              {selectedPack.name}
            </button>
            <button
              type="button"
              className={styles.myPackIconBtn}
              title="Fork in Node Factory"
              aria-label={`Fork ${selectedPack.name} in Node Factory`}
              disabled={busy}
              onClick={() => onOpenForkInFactory(selectedPack)}
            >
              <FontAwesomeIcon icon={faPenToSquare} />
            </button>
          </div>
          <p className={styles.hubForkFamilyRailMeta}>
            Family root {family.rootKey} · {family.members.length} forks
          </p>
        </div>
      </div>

      <label className={styles.hubForkFamilySelectLabel}>
        Fork Family
        <ForkFamilyPicker
          variant="hub"
          rootKey={family.rootKey}
          options={forkPickerOptions}
          value={resolvedDir}
          onChange={onForkPicked}
        />
      </label>

      <div role="list">
        {family.members.map((pack) => (
          <div
            key={pack.dirName}
            role="listitem"
            className={`${styles.myPackRow} ${
              pack.dirName === resolvedDir ? styles.myPackRowHighlight : ""
            }`}
          >
            <div>
              <div className={styles.myPackTitleBlock}>
                <div className={styles.myPackNameRow}>
                  <button
                    type="button"
                    className={styles.myPackFactoryNameBtn}
                    title="Fork in Node Factory (new install; source unchanged)"
                    onClick={() => onOpenForkInFactory(pack)}
                  >
                    {pack.name}
                  </button>
                  <button
                    type="button"
                    className={styles.myPackIconBtn}
                    title="Fork in Node Factory"
                    aria-label={`Fork ${pack.name} in Node Factory`}
                    disabled={busy}
                    onClick={() => onOpenForkInFactory(pack)}
                  >
                    <FontAwesomeIcon icon={faPenToSquare} />
                  </button>
                </div>
                <CatalogPublishPill
                  variant="hub"
                  dirName={pack.dirName}
                  published={catalogPublishedDirs.has(pack.dirName)}
                  allowPublish={catalogPublishAllowed}
                  busy={publishingPackKey === pack.dirName}
                  onPublish={onPublishToCatalog}
                />
              </div>
              <span className={styles.myPackVersion}>
                {pack.packId} · v{pack.version}
              </span>
              {pack.lineage?.forkedFrom ? (
                <p className={styles.hubForkOfLine}>
                  {formatForkOfSubtitle(pack.lineage).text}
                </p>
              ) : null}
            </div>

            <MyPackIconActions
              pack={pack}
              busy={busy}
              paletteDockBusy={paletteDockBusy}
              onExport={onExport}
              onUninstall={onUninstall}
              onPaletteDockToggle={onPaletteDockToggle}
            />
          </div>
        ))}
      </div>
    </section>
  );
});


