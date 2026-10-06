import React, { useMemo, useSyncExternalStore } from "react";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { groupPalettePackages } from "../../menus/nodes/toolsMenuPackagePalette/model";
import { SAVE_AS_NEW_PACK } from "../../../utils/palettePackageFactoryDraft";
import styles from "./NodeSaveAsModal.module.css";

const NOOP = () => () => {};

function registryBootstrapKey(): string {
  return String(getPaletteNodeTypes().length);
}

export interface PackageTargetOption {
  /** `<packageId>@<major>`. */
  sectionKey: string;
  displayName: string;
}

/**
 * The installed packages a template can be saved into: the project's palette
 * packages that are not read-only. `registryKey` changes whenever the node
 * registry does. Shared by Save as package node and New node from a Python
 * function.
 */
export function useWritablePackageOptions(): { options: PackageTargetOption[]; registryKey: string } {
  const registryKey = useSyncExternalStore(
    typeof window !== "undefined" ? subscribeToRegistry : NOOP,
    registryBootstrapKey,
    () => "ssr",
  );
  const options = useMemo(() => {
    const packageTypes = getPaletteNodeTypes().filter((d) => d.source === "package");
    return groupPalettePackages(packageTypes)
      .filter((g) => g.descriptors[0]?.package?.readOnly !== true)
      .map((g) => ({
        sectionKey: g.key,
        displayName: g.descriptors[0]?.package?.name?.trim() || g.label,
      }));
  }, [registryKey]);
  return { options, registryKey };
}

/**
 * The destination of a template: "New package…" with its name, or one of
 * *options*. *children* show under an installed destination. Element ids are
 * `<idPrefix>-package-target` and `<idPrefix>-new-package-name`.
 */
export function PackageTargetPicker({
  idPrefix,
  options,
  targetKey,
  onTargetKey,
  newPackageName,
  onNewPackageName,
  busy,
  children,
}: {
  idPrefix: string;
  options: PackageTargetOption[];
  targetKey: string;
  onTargetKey: (key: string) => void;
  newPackageName: string;
  onNewPackageName: (name: string) => void;
  busy: boolean;
  children?: React.ReactNode;
}) {
  return (
    <>
      <label className={styles.fieldLabel} htmlFor={`${idPrefix}-package-target`}>
        Destination package
      </label>
      <div className={styles.selectWrap}>
        <select
          id={`${idPrefix}-package-target`}
          className={styles.select}
          value={targetKey}
          disabled={busy}
          onChange={(e) => onTargetKey(e.target.value)}
        >
          <option value={SAVE_AS_NEW_PACK}>New package…</option>
          {options.map((opt) => (
            <option key={opt.sectionKey} value={opt.sectionKey}>
              {opt.displayName}
            </option>
          ))}
        </select>
        <span className={styles.selectChevron} aria-hidden>
          ▼
        </span>
      </div>

      {targetKey === SAVE_AS_NEW_PACK ? (
        <div className={styles.newPackageField}>
          <label className={styles.fieldLabel} htmlFor={`${idPrefix}-new-package-name`}>
            New package name
          </label>
          <input
            id={`${idPrefix}-new-package-name`}
            className={styles.input}
            value={newPackageName}
            disabled={busy}
            onChange={(e) => onNewPackageName(e.target.value)}
            placeholder="My analytics package"
          />
        </div>
      ) : (
        children
      )}
    </>
  );
}
