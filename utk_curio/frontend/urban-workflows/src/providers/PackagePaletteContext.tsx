import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

const DRAFT_PREFIX = '__draft__:';

export const PALETTE_DRAFT_KEY_PREFIX = DRAFT_PREFIX;

/** One staging row: stable React key + canvas node id (same node may appear multiple times). */
export type PackageStagedRow = {
  rowId: string;
  canvasNodeId: string;
};

export function paletteDraftUuidFromSectionKey(sectionKey: string): string | undefined {
  if (!sectionKey.startsWith(DRAFT_PREFIX)) return undefined;
  return sectionKey.slice(DRAFT_PREFIX.length);
}
export function draftPackageSectionKey(draftUuid: string): string {
  return `${DRAFT_PREFIX}${draftUuid}`;
}

export function isDraftPackageSectionKey(key: string): boolean {
  return key.startsWith(DRAFT_PREFIX);
}

function makeStagedRowId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `row-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export type PackagePaletteContextValue = {
  activePackageKey: string | null;
  setActivePackageKey: (key: string | null) => void;
  packagesPaletteEditMode: boolean;
  setPackagesPaletteEditMode: (on: boolean) => void;

  /** `packageId@major` targeted for reveal (scroll/expand); consumed after handling; cleared when that panel closes. */
  paletteDockRevealCoord: string | null;
  setPaletteDockRevealCoord: (coord: string | null) => void;

  draftPackageSectionIds: readonly string[];
  registerDraftPackageSection: () => void;

  stagedRowsByPackageKey: Readonly<Record<string, readonly PackageStagedRow[]>>;
  stageCanvasNodeOnPackageSection: (
    packageSectionKey: string,
    canvasNodeId: string,
    options?: {
      /** Remove other staged rows whose canvas nodes share this label (case-insensitive). */
      dedupeByLabel?: string;
      labelForNodeId?: (nodeId: string) => string | undefined;
    },
  ) => void;
  removeStagedRowFromSection: (packageSectionKey: string, rowId: string) => void;

  /** Kind ids marked for removal while editing a package section (cleared when edit mode exits). */
  removedKindIdsByPackageKey: Readonly<Record<string, readonly string[]>>;
  removeKindFromPackageSection: (packageSectionKey: string, kindId: string) => void;
};

const PackagePaletteContext = createContext<PackagePaletteContextValue | null>(null);

function normalizeKindLabel(label: string): string {
  return label.trim().toLowerCase();
}

export function PackagePaletteProvider({ children }: { children: React.ReactNode }) {
  const [activePackageKey, setActivePackageKey] = useState<string | null>(null);
  const [paletteDockRevealCoord, setPaletteDockRevealCoord] = useState<string | null>(null);
  const [packagesPaletteEditMode, setPackagesPaletteEditMode] = useState(false);
  const [draftPackageSectionIds, setDraftPackageSectionIds] = useState<string[]>([]);
  const [stagedRowsByPackageKey, setStagedRowsByPackageKey] = useState<Record<string, PackageStagedRow[]>>({});
  const [removedKindIdsByPackageKey, setRemovedKindIdsByPackageKey] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!packagesPaletteEditMode) {
      setDraftPackageSectionIds([]);
      setStagedRowsByPackageKey({});
      setRemovedKindIdsByPackageKey({});
    }
  }, [packagesPaletteEditMode]);

  const registerDraftPackageSection = useCallback(() => {
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `draft-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setDraftPackageSectionIds((prev) => [id, ...prev]);
    setActivePackageKey(draftPackageSectionKey(id));
  }, []);

  const stageCanvasNodeOnPackageSection = useCallback(
    (
      packageSectionKey: string,
      canvasNodeId: string,
      options?: {
        dedupeByLabel?: string;
        labelForNodeId?: (nodeId: string) => string | undefined;
      },
    ) => {
      const trimmed = canvasNodeId.trim();
      if (!trimmed) return;
      const row: PackageStagedRow = { rowId: makeStagedRowId(), canvasNodeId: trimmed };
      setStagedRowsByPackageKey((prev) => {
        let list = prev[packageSectionKey] ?? [];
        const dedupe = options?.dedupeByLabel?.trim();
        if (dedupe && options?.labelForNodeId) {
          const norm = normalizeKindLabel(dedupe);
          list = list.filter((r) => {
            if (r.canvasNodeId === trimmed) return false;
            const otherLabel = options.labelForNodeId!(r.canvasNodeId);
            return normalizeKindLabel(otherLabel ?? "") !== norm;
          });
        }
        return { ...prev, [packageSectionKey]: [...list, row] };
      });
    },
    [],
  );

  const removeStagedRowFromSection = useCallback((packageSectionKey: string, rowId: string) => {
    setStagedRowsByPackageKey((prev) => {
      const prevList = prev[packageSectionKey];
      if (!prevList?.length) return prev;
      const nextList = prevList.filter((r) => r.rowId !== rowId);
      if (nextList.length === 0) {
        const { [packageSectionKey]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [packageSectionKey]: nextList };
    });
  }, []);

  const removeKindFromPackageSection = useCallback((packageSectionKey: string, kindId: string) => {
    const trimmed = kindId.trim();
    if (!trimmed) return;
    setRemovedKindIdsByPackageKey((prev) => {
      const existing = prev[packageSectionKey] ?? [];
      if (existing.includes(trimmed)) return prev;
      return { ...prev, [packageSectionKey]: [...existing, trimmed] };
    });
  }, []);

  const value: PackagePaletteContextValue = useMemo(
    () => ({
      activePackageKey,
      setActivePackageKey,
      packagesPaletteEditMode,
      setPackagesPaletteEditMode,
      paletteDockRevealCoord,
      setPaletteDockRevealCoord,
      draftPackageSectionIds,
      registerDraftPackageSection,
      stagedRowsByPackageKey,
      stageCanvasNodeOnPackageSection,
      removeStagedRowFromSection,
      removedKindIdsByPackageKey,
      removeKindFromPackageSection,
    }),
    [
      activePackageKey,
      packagesPaletteEditMode,
      paletteDockRevealCoord,
      draftPackageSectionIds,
      registerDraftPackageSection,
      stagedRowsByPackageKey,
      stageCanvasNodeOnPackageSection,
      removeStagedRowFromSection,
      removedKindIdsByPackageKey,
      removeKindFromPackageSection,
    ],
  );

  return <PackagePaletteContext.Provider value={value}>{children}</PackagePaletteContext.Provider>;
}

export function usePackagePalette(): PackagePaletteContextValue {
  const ctx = useContext(PackagePaletteContext);
  if (!ctx) {
    throw new Error('usePackagePalette must be used within a PackagePaletteProvider');
  }
  return ctx;
}
