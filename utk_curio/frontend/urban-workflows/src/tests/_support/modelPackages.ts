import type { PackagePayload, PackageTemplatePayload } from "../../services/packages";

/**
 * Package rows as `GET /api/packages/catalog` and `GET /api/packages` list
 * them: the model packages the Model Catalog shows (kind `model`, with their
 * `model` block) and node packages, which only the Node Catalog shows.
 *
 * Built loosely and cast, so the rows can carry the fields a listing adds
 * (`modules`, `model.downloadsOnFirstUse`) whatever the type says.
 */

export function template(over: Partial<PackageTemplatePayload> = {}): PackageTemplatePayload {
  return {
    id: "pkg/node@1",
    templateId: "node",
    label: "Node",
    category: "computation",
    engine: "python",
    description: "",
    icon: null,
    iconRef: null,
    behavior: null,
    paletteOrder: null,
    editor: "code",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    grammarId: null,
    badge: null,
    inputPorts: [],
    outputPorts: [],
    source: null,
    bidirectional: false,
    containerStyle: null,
    hasProvenance: null,
    ...over,
  };
}

function row(fields: Record<string, unknown>): PackagePayload {
  return {
    major: 1,
    version: "1.0.0",
    publisher: "Curio",
    description: "",
    license: "MIT",
    permissions: [],
    dependencies: { packages: {}, python: {}, js: {} },
    templates: [],
    lineage: null,
    channel: "stable",
    createdAtMs: 0,
    modules: [],
    ...fields,
    familyKey: fields.dirName,
  } as unknown as PackagePayload;
}

/** DDRNet23-Slim, which ships with Curio: a segmentation model with the
 *  text of its weights' license, and Image Segmentation as its node. */
export function ddrnetPackage(over: Record<string, unknown> = {}): PackagePayload {
  return row({
    packageId: "model.curio.ddrnet23-slim",
    dirName: "model.curio.ddrnet23-slim@1",
    name: "DDRNet23-Slim (street scenes)",
    description: "Labels every pixel of a street photo.",
    kind: "model",
    readOnly: true,
    dependencies: { packages: {}, python: { onnxruntime: ">=1.17" }, js: {} },
    templates: [
      template({
        id: "model.curio.ddrnet23-slim/image-segmentation@1",
        templateId: "image-segmentation",
        label: "Image Segmentation",
      }),
    ],
    model: {
      type: "semantic-segmentation",
      runtime: "onnx",
      entry: "models/ddrnet23_slim.onnx",
      labels: Array.from({ length: 19 }, (_, i) => ["road", "sidewalk", "building"][i] ?? `class ${i}`),
      sizeBytes: 23_076_949,
      license: "MIT; trained on Cityscapes",
      licenseFile: "LICENSE",
      publisher: "DDRNet authors",
      homepage: "https://huggingface.co/qualcomm/DDRNet23-Slim",
      input: { width: 2048, height: 1024, dtype: "uint8", layout: "NCHW", scale: 1 },
      downloadsOnFirstUse: false,
    },
    createdAt: "2026-10-01T00:00:00Z",
    ...over,
  });
}

/** Deep Umbra: an image-to-image model whose node imports its package's
 *  module, `deep_umbra`, and whose weights a pip install fetches on first use. */
export function deepUmbraPackage(over: Record<string, unknown> = {}): PackagePayload {
  return row({
    packageId: "model.scout.deep-umbra",
    dirName: "model.scout.deep-umbra@1",
    name: "Deep Umbra (accumulated shadows)",
    description: "SCOUT's shadow model.",
    kind: "model",
    readOnly: true,
    modules: ["deep_umbra"],
    templates: [
      template({
        id: "model.scout.deep-umbra/accumulated-shadow@1",
        templateId: "accumulated-shadow",
        label: "Accumulated Shadow",
        source: "sources/accumulated-shadow.py",
      }),
    ],
    model: {
      type: "image-to-image",
      runtime: "onnx",
      entry: "models/deep_umbra.onnx",
      labels: [],
      sizeBytes: 10_534_492,
      license: "Used with the permission of SCOUT's authors",
      publisher: "SCOUT (urban-toolkit/scout)",
      homepage: "https://github.com/urban-toolkit/scout",
      input: { width: 512, height: 512, dtype: "float32", layout: "NHWC", scale: 1 },
      downloadsOnFirstUse: true,
    },
    ...over,
  });
}

/** A model this account downloaded from the Discovery Catalog: in its store
 *  only, never in the shared catalog. */
export function importedModelPackage(over: Record<string, unknown> = {}): PackagePayload {
  return row({
    packageId: "imported.xabc123def456",
    dirName: "imported.xabc123def456@1",
    name: "SegFormer B0 (ADE20K)",
    publisher: "NVIDIA",
    description: "A Transformers checkpoint.",
    kind: "model",
    templates: [
      template({
        id: "imported.xabc123def456/image-segmentation@1",
        templateId: "image-segmentation",
        label: "Image Segmentation",
      }),
    ],
    model: {
      type: "semantic-segmentation",
      runtime: "transformers",
      entry: "models/checkpoint",
      labels: ["wall", "floor"],
      sizeBytes: 15 * 1024 * 1024,
      license: "Apache-2.0",
      publisher: "NVIDIA",
      downloadsOnFirstUse: false,
      discoverySource: {
        sourceId: "source.curio.huggingface",
        sourceName: "Hugging Face",
        resourceId: "nvidia/segformer-b0-finetuned-ade-512-512",
      },
    },
    createdAt: "2026-09-30T12:00:00Z",
    ...over,
  });
}

/** A node package that ships a module of its own. */
export function scoutPackage(over: Record<string, unknown> = {}): PackagePayload {
  return row({
    packageId: "curio.scout",
    dirName: "curio.scout@1",
    name: "Scout",
    kind: "node",
    modules: ["scout_rasters"],
    templates: [
      template({
        id: "curio.scout/rasterize-buildings@1",
        templateId: "rasterize-buildings",
        label: "Rasterize Buildings",
      }),
    ],
    ...over,
  });
}

/** Curio's own nodes, in every dataflow. */
export function builtinPackage(over: Record<string, unknown> = {}): PackagePayload {
  return row({
    packageId: "curio.builtin",
    dirName: "curio.builtin@1",
    name: "Curio built-in nodes",
    kind: "node",
    readOnly: true,
    templates: [template({ id: "curio.builtin/data-loading@1", templateId: "data-loading", label: "Data Loading" })],
    ...over,
  });
}
