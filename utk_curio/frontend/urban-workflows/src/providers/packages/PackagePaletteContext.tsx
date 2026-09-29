import React, {
  createContext,
  useContext,
  useMemo,
  useState,
} from 'react';

export type PackagePaletteContextValue = {
  activePackageKey: string | null;
  setActivePackageKey: (key: string | null) => void;

  /** `packageId@major` targeted for reveal (scroll/expand); consumed after handling; cleared when that panel closes. */
  paletteDockRevealCoord: string | null;
  setPaletteDockRevealCoord: (coord: string | null) => void;
};

const PackagePaletteContext = createContext<PackagePaletteContextValue | null>(null);

export function PackagePaletteProvider({ children }: { children: React.ReactNode }) {
  const [activePackageKey, setActivePackageKey] = useState<string | null>(null);
  const [paletteDockRevealCoord, setPaletteDockRevealCoord] = useState<string | null>(null);

  const value: PackagePaletteContextValue = useMemo(
    () => ({
      activePackageKey,
      setActivePackageKey,
      paletteDockRevealCoord,
      setPaletteDockRevealCoord,
    }),
    [activePackageKey, paletteDockRevealCoord],
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
