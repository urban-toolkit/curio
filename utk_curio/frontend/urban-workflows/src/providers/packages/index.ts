/**
 * The packages providers (memo dev/143, F2): the Node Catalog drawer provider, the
 * palette context, and the two hooks that compose the layer with the node-kind
 * registry — the sideload pathway and the dataflow's declared-dependency loader.
 * They live here, not in `services/packages`, because both call
 * `refreshPackageRegistry` after an install and the layer never imports `registry/`.
 */
export * from "./NodeCatalogDrawerProvider";
export * from "./PackagePaletteContext";
export * from "./usePackageArchiveImport";
export * from "./useEnsureWorkflowDeps";
