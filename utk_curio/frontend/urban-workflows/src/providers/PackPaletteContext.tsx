import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

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

  draftPackSectionIds: readonly string[];
  registerDraftPackSection: () => void;

  stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
  stageCanvasNodeOnPackSection: (packSectionKey: string, canvasNodeId: string) => void;
  removeStagedRowFromSection: (packSectionKey: string, rowId: string) => void;
};

const PackPaletteContext = createContext<PackPaletteContextValue | null>(null);

export function PackPaletteProvider({ children }: { children: React.ReactNode }) {
  const [activePackKey, setActivePackKey] = useState<string | null>(null);
  const [packsPaletteEditMode, setPacksPaletteEditMode] = useState(false);
  const [draftPackSectionIds, setDraftPackSectionIds] = useState<string[]>([]);
  const [stagedRowsByPackKey, setStagedRowsByPackKey] = useState<Record<string, PackStagedRow[]>>({});

  useEffect(() => {
    if (!packsPaletteEditMode) {
      setDraftPackSectionIds([]);
      setStagedRowsByPackKey({});
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

  const stageCanvasNodeOnPackSection = useCallback((packSectionKey: string, canvasNodeId: string) => {
    const trimmed = canvasNodeId.trim();
    if (!trimmed) return;
    const row: PackStagedRow = { rowId: makeStagedRowId(), canvasNodeId: trimmed };
    setStagedRowsByPackKey((prev) => ({
      ...prev,
      [packSectionKey]: [...(prev[packSectionKey] ?? []), row],
    }));
  }, []);

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

  const value: PackPaletteContextValue = useMemo(
    () => ({
      activePackKey,
      setActivePackKey,
      packsPaletteEditMode,
      setPacksPaletteEditMode,
      draftPackSectionIds,
      registerDraftPackSection,
      stagedRowsByPackKey,
      stageCanvasNodeOnPackSection,
      removeStagedRowFromSection,
    }),
    [
      activePackKey,
      packsPaletteEditMode,
      draftPackSectionIds,
      registerDraftPackSection,
      stagedRowsByPackKey,
      stageCanvasNodeOnPackSection,
      removeStagedRowFromSection,
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
