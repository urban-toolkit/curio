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
export type PackStagedRow = {
  rowId: string;
  canvasNodeId: string;
};

export function paletteDraftUuidFromSectionKey(sectionKey: string): string | undefined {
  if (!sectionKey.startsWith(DRAFT_PREFIX)) return undefined;
  return sectionKey.slice(DRAFT_PREFIX.length);
}
export function draftPackSectionKey(draftUuid: string): string {
  return `${DRAFT_PREFIX}${draftUuid}`;
}

export function isDraftPackSectionKey(key: string): boolean {
  return key.startsWith(DRAFT_PREFIX);
}

function makeStagedRowId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `row-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export type PackPaletteContextValue = {
  activePackKey: string | null;
  setActivePackKey: (key: string | null) => void;
  packsPaletteEditMode: boolean;
  setPacksPaletteEditMode: (on: boolean) => void;

  /** `packId@major` targeted for reveal (scroll/expand); consumed after handling; cleared when that panel closes. */
  paletteDockRevealCoord: string | null;
  setPaletteDockRevealCoord: (coord: string | null) => void;

  draftPackSectionIds: readonly string[];
  registerDraftPackSection: () => void;

  stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
  stageCanvasNodeOnPackSection: (
    packSectionKey: string,
    canvasNodeId: string,
    options?: {
      /** Remove other staged rows whose canvas nodes share this label (case-insensitive). */
      dedupeByLabel?: string;
      labelForNodeId?: (nodeId: string) => string | undefined;
    },
  ) => void;
  removeStagedRowFromSection: (packSectionKey: string, rowId: string) => void;

  /** Kind ids marked for removal while editing a pack section (cleared when edit mode exits). */
  removedKindIdsByPackKey: Readonly<Record<string, readonly string[]>>;
  removeKindFromPackSection: (packSectionKey: string, kindId: string) => void;
};

const PackPaletteContext = createContext<PackPaletteContextValue | null>(null);

function normalizeKindLabel(label: string): string {
  return label.trim().toLowerCase();
}

export function PackPaletteProvider({ children }: { children: React.ReactNode }) {
  const [activePackKey, setActivePackKey] = useState<string | null>(null);
  const [paletteDockRevealCoord, setPaletteDockRevealCoord] = useState<string | null>(null);
  const [packsPaletteEditMode, setPacksPaletteEditMode] = useState(false);
  const [draftPackSectionIds, setDraftPackSectionIds] = useState<string[]>([]);
  const [stagedRowsByPackKey, setStagedRowsByPackKey] = useState<Record<string, PackStagedRow[]>>({});
  const [removedKindIdsByPackKey, setRemovedKindIdsByPackKey] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!packsPaletteEditMode) {
      setDraftPackSectionIds([]);
      setStagedRowsByPackKey({});
      setRemovedKindIdsByPackKey({});
    }
  }, [packsPaletteEditMode]);

  const registerDraftPackSection = useCallback(() => {
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `draft-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setDraftPackSectionIds((prev) => [id, ...prev]);
    setActivePackKey(draftPackSectionKey(id));
  }, []);

  const stageCanvasNodeOnPackSection = useCallback(
    (
      packSectionKey: string,
      canvasNodeId: string,
      options?: {
        dedupeByLabel?: string;
        labelForNodeId?: (nodeId: string) => string | undefined;
      },
    ) => {
      const trimmed = canvasNodeId.trim();
      if (!trimmed) return;
      const row: PackStagedRow = { rowId: makeStagedRowId(), canvasNodeId: trimmed };
      setStagedRowsByPackKey((prev) => {
        let list = prev[packSectionKey] ?? [];
        const dedupe = options?.dedupeByLabel?.trim();
        if (dedupe && options?.labelForNodeId) {
          const norm = normalizeKindLabel(dedupe);
          list = list.filter((r) => {
            if (r.canvasNodeId === trimmed) return false;
            const otherLabel = options.labelForNodeId!(r.canvasNodeId);
            return normalizeKindLabel(otherLabel ?? "") !== norm;
          });
        }
        return { ...prev, [packSectionKey]: [...list, row] };
      });
    },
    [],
  );

  const removeStagedRowFromSection = useCallback((packSectionKey: string, rowId: string) => {
    setStagedRowsByPackKey((prev) => {
      const prevList = prev[packSectionKey];
      if (!prevList?.length) return prev;
      const nextList = prevList.filter((r) => r.rowId !== rowId);
      if (nextList.length === 0) {
        const { [packSectionKey]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [packSectionKey]: nextList };
    });
  }, []);

  const removeKindFromPackSection = useCallback((packSectionKey: string, kindId: string) => {
    const trimmed = kindId.trim();
    if (!trimmed) return;
    setRemovedKindIdsByPackKey((prev) => {
      const existing = prev[packSectionKey] ?? [];
      if (existing.includes(trimmed)) return prev;
      return { ...prev, [packSectionKey]: [...existing, trimmed] };
    });
  }, []);

  const value: PackPaletteContextValue = useMemo(
    () => ({
      activePackKey,
      setActivePackKey,
      packsPaletteEditMode,
      setPacksPaletteEditMode,
      paletteDockRevealCoord,
      setPaletteDockRevealCoord,
      draftPackSectionIds,
      registerDraftPackSection,
      stagedRowsByPackKey,
      stageCanvasNodeOnPackSection,
      removeStagedRowFromSection,
      removedKindIdsByPackKey,
      removeKindFromPackSection,
    }),
    [
      activePackKey,
      packsPaletteEditMode,
      paletteDockRevealCoord,
      draftPackSectionIds,
      registerDraftPackSection,
      stagedRowsByPackKey,
      stageCanvasNodeOnPackSection,
      removeStagedRowFromSection,
      removedKindIdsByPackKey,
      removeKindFromPackSection,
    ],
  );

  return <PackPaletteContext.Provider value={value}>{children}</PackPaletteContext.Provider>;
}

export function usePackPalette(): PackPaletteContextValue {
  const ctx = useContext(PackPaletteContext);
  if (!ctx) {
    throw new Error('usePackPalette must be used within a PackPaletteProvider');
  }
  return ctx;
}
