/**
 * Model packages: packages of kind `model`, which ship their weights under
 * `models/` and show in the Model Catalog, never in the Node Catalog. The
 * Model Catalog lists them through this layer as the Node Catalog lists node
 * packages (`usePackageCatalog` with `packageKind: "model"`); the palette and
 * a Discovery add use the pieces below.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { packagesApi } from "./packagesApi";
import { catalogAndOwnPackages } from "./packageListUtils";
import type { ModelBlockPayload, PackageKind, PackagePayload } from "./types";

/** A package's kind: `node` unless its manifest says `model`. */
export function packageKindOf(pkg: Pick<PackagePayload, "kind">): PackageKind {
  return pkg.kind === "model" ? "model" : "node";
}

/** A model package with its `model` block. */
export function isModelPackage(
  pkg: PackagePayload,
): pkg is PackagePayload & { kind: "model"; model: ModelBlockPayload } {
  return pkg.kind === "model" && pkg.model != null;
}

export const MODEL_RUNTIME_LABEL: Record<ModelBlockPayload["runtime"], string> = {
  onnx: "ONNX",
  transformers: "Transformers",
};

export const MODEL_TYPE_LABEL: Record<ModelBlockPayload["type"], string> = {
  "semantic-segmentation": "Semantic segmentation",
  "image-to-image": "Image to image",
  "node-regression": "Node regression",
};

/** Dispatched after anything that changes the packages an account holds
 *  outside a catalog surface's own actions (a Discovery add), so every
 *  mounted listing reloads. */
export const PACKAGE_CATALOG_REFRESH_EVENT = "curio:package-catalog-refresh";

export function notifyPackageCatalogRefresh(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PACKAGE_CATALOG_REFRESH_EVENT));
}

/** Calls *reload* whenever `notifyPackageCatalogRefresh` fires, while *enabled*. */
export function usePackageCatalogRefresh(reload: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    window.addEventListener(PACKAGE_CATALOG_REFRESH_EVENT, reload);
    return () => window.removeEventListener(PACKAGE_CATALOG_REFRESH_EVENT, reload);
  }, [enabled, reload]);
}

export interface UseModelPackagesResult {
  /** Every model package the account can use: the catalog's and its own. */
  models: PackagePayload[];
  loading: boolean;
  /** Present only when the listing failed; the last rows stay. */
  error: string | null;
  reload: () => void;
}

/**
 * The model packages an account can use, for a surface that lists them
 * without acting on a dataflow (the palette): the catalog's and the
 * account's own, once each, as the Model Catalog's Browse all lists them.
 */
export function useModelPackages(): UseModelPackagesResult {
  const [models, setModels] = useState<PackagePayload[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  // A slow first answer must not overwrite a later one.
  const latest = useRef(0);

  useEffect(() => {
    const ticket = ++latest.current;
    setLoading(true);
    Promise.all([packagesApi.catalog("model"), packagesApi.listInstalled("model")])
      .then(([catalog, installed]) => {
        if (ticket !== latest.current) return;
        setModels(
          catalogAndOwnPackages(catalog.packages, installed.packages).filter(isModelPackage),
        );
        setError(null);
      })
      .catch((err: Error) => {
        if (ticket !== latest.current) return;
        setError(err?.message || "Could not load the Model Catalog.");
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  usePackageCatalogRefresh(reload);
  return { models, loading, error, reload };
}
