/**
 * A package on the wire: templates, ports, lineage, dependencies, the payload and its metadata PATCH body.
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

export interface PortPayload {
  types: string[];
  cardinality?: string;
}

export interface PackageTemplatePayload {
  id: string; // canonical "<packageId>/<templateId>@<major>"
  templateId: string;
  label: string;
  category: string;
  engine: "python" | "javascript";
  description: string;
  icon: string | null;
  /** "<source>:<icon-id>" key resolved through iconRegistry. */
  iconRef: string | null;
  /** String key into the behaviorRegistry. */
  behavior: string | null;
  /** Sort order in the palette; null means built-in default ordering. */
  paletteOrder: number | null;
  editor: "code" | "widgets" | "grammar" | "none";
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  /** Grammar adapter key (e.g. "vega-lite") when editor === "grammar". */
  grammarId: string | null;
  /** Palette card badge label (e.g. "VEGA", "AUTK"). */
  badge: string | null;
  inputPorts: PortPayload[];
  outputPorts: PortPayload[];
  /** Package-relative path to the optional starter source file. */
  source: string | null;
  /** #662: the widgets a freshly dropped node starts with (metadata.widgets shape). */
  widgets?: unknown[] | null;
  /** Adds a third `'in/out'` handle on top of the standard in/out pair (interaction-loop templates). */
  bidirectional: boolean;
  /** Overrides for the canvas container layout (size, no-content, play-button gate). */
  containerStyle: {
    nodeWidth?: number;
    nodeHeight?: number;
    noContent?: boolean;
    disablePlay?: boolean;
  } | null;
  /** When false, suppresses the provenance editor tab; null = client default (true). */
  hasProvenance: boolean | null;
  /** dev/91: declared backend handler this template's Run invokes through
   * the package backend sandbox (null/absent = ordinary execution). */
  backendHandler?: string | null;
  /** Whether a node of this template loads the dataset it names. */
  loadsDataset?: boolean;
  /** Whether a node of this template shows only its controls on its Widgets
   *  tab, and opens there. */
  opensOnControls?: boolean;
}


/** Package-relative coordinate (`packageId` + compatibility major). */
export interface PackageLineageCoordPayload {
  packageId: string;
  major: number;
}

/** Fork provenance from manifest `lineage`; surfaced by `/api/packages`. */
export interface PackageLineagePayload {
  forkedFrom: PackageLineageCoordPayload;
  root: PackageLineageCoordPayload;
}

export interface PackageDependencies {
  packages: Record<string, string>;
  python: Record<string, string>;
  js: Record<string, string>;
}

/** `model` for a model package, which ships its weights under `models/` and
 *  shows in the Model Catalog; `node` for every other package, which shows in
 *  the Node Catalog. */
export type PackageKind = "node" | "model";

/** How a model package's weights run: its manifest's `model` block. */
export interface ModelBlockPayload {
  type: "semantic-segmentation" | "image-to-image" | "node-regression";
  runtime: "onnx" | "transformers";
  /** The weights under `models/`. */
  entry: string;
  labels: string[];
  sizeBytes: number;
  /** The weights' license; the package's `license` is its code's. */
  license: string;
  publisher: string;
  input?: {
    width: number;
    height: number;
    dtype: "uint8" | "float32";
    layout: "NCHW" | "NHWC";
    scale: number;
    mean?: number[];
    std?: number[];
  };
  licenseFile?: string;
  homepage?: string;
  discoverySource?: Record<string, unknown>;
  /** Listings only: a pip install has left the weights out and no node has
   *  fetched them yet, so the first run downloads them. */
  downloadsOnFirstUse?: boolean;
}

export interface PackagePayload {
  packageId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string | null;
  permissions: string[];
  dependencies: PackageDependencies;
  templates: PackageTemplatePayload[];
  dirName: string;
  /** Fork provenance when declared in manifest; otherwise null from API. */
  lineage: PackageLineagePayload | null;
  /** Canonical catalog family key (`lineage.root` coordinate or `dirName`). */
  familyKey: string;
  /** Normalised from manifest `distribution.channel` (default stable). */
  channel: string;
  /** Catalog endpoint only — true when the user already has this coord installed. */
  installed?: boolean;
  /**
   * ISO 8601 instant from manifest ``createdAt``. Omitted only for malformed legacy rows.
   */
  createdAt?: string;
  /**
   * Epoch milliseconds for ``manifest.createdAt`` (canonical package creation / authoring time).
   * Zero when absent; API lists sort newest-first primarily by this field.
   */
  createdAtMs?: number;
  /**
   * Epoch ms of ``manifest.json`` filesystem mtime (diagnostic — not used for canonical ordering).
   */
  installUpdatedAtMs?: number;
  /**
   * README body, capped to 64 KiB by the backend. Surfaced by ``_manifest_to_payload``
   * for installed packages only (catalog rows omit it). Used by ``PackageMetadataModal``
   * to pre-populate the README field.
   */
  readme?: string;
  /** When the manifest's package is read-only (e.g. ``curio.builtin@1``). */
  readOnly?: boolean;
  /** The package's own interface bundle (``scripts/behaviors.js``), when it ships one. */
  behaviorScript?: string;
  /** `model` for a model package, which ships its weights under `models/`; else `node`. */
  kind?: PackageKind;
  /** A model package's `model` block. */
  model?: ModelBlockPayload;
  /** Listings only: the Python modules the package ships under `sources/`,
   *  which its nodes import (`deep_umbra`). */
  modules?: string[];
  /** The store listing asked with `usage` only: whether one of the account's
   *  dataflows uses the package (its lockfile names it). A catalog page offers
   *  Remove from account only when this is `false`. */
  inUse?: boolean;
  /**
   * Catalog endpoint only - whether THIS user published it, and may therefore
   * withdraw it. The peer of `AgentCard.publishable`.
   *
   * The UI used to gate Unpublish on `readOnly !== true`, which is not the same
   * question: `readOnly` is an author's opt-in that almost no manifest sets, so
   * the gate matched nearly every package and offered Unpublish on ones that
   * shipped with the deployment. Computed by the backend from the publisher
   * record, and enforced there too - the unpublish route now 403s a
   * non-publisher rather than trusting this flag.
   */
  publishable?: boolean;
}

/** Partial-update body for `PATCH /api/packages/<dirName>` (metadata editor). */
export interface PackageMetadataUpdate {
  name?: string;
  description?: string;
  publisher?: string;
  license?: string | null;
  permissions?: string[];
  readme?: string;
  compatibility?: { curioRuntime?: string };
}
