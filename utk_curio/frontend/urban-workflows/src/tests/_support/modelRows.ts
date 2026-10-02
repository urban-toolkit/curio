import type { ModelRow } from "../../services/modelCatalog";

/** The model Curio ships today, as `GET /api/models/catalog` lists it. */
export function shippedModel(over: Partial<ModelRow> = {}): ModelRow {
  return {
    id: "model.curio.ddrnet23-slim",
    dirName: "model.curio.ddrnet23-slim@1",
    name: "DDRNet23-Slim (street scenes)",
    version: "1.0.0",
    description: "Labels every pixel of a street photo.",
    publisher: "Curio",
    homepage: "https://github.com/ydhongHIT/DDRNet",
    license: "MIT; trained on Cityscapes",
    hasLicenseText: true,
    runtime: "onnx",
    task: "semantic-segmentation",
    labels: ["road", "sidewalk", "building"],
    labelCount: 3,
    input: { width: 1024, height: 512, dtype: "uint8" },
    sizeBytes: 23 * 1024 * 1024,
    tags: ["cityscapes", "street"],
    origin: "shipped",
    createdAt: null,
    ...over,
  };
}

/** A model this account downloaded from the Discovery Catalog. */
export function downloadedModel(over: Partial<ModelRow> = {}): ModelRow {
  return shippedModel({
    id: "imported.xabc123def456",
    dirName: "imported.xabc123def456@1",
    name: "SegFormer B0 (ADE20K)",
    publisher: "NVIDIA",
    description: "A Transformers checkpoint.",
    homepage: null,
    license: "Apache-2.0",
    hasLicenseText: false,
    runtime: "transformers",
    labels: ["wall", "floor"],
    labelCount: 2,
    input: undefined,
    sizeBytes: 15 * 1024 * 1024,
    tags: ["ade20k"],
    origin: "downloaded",
    createdAt: "2026-09-30T12:00:00Z",
    discoverySource: {
      sourceId: "source.curio.huggingface",
      sourceName: "Hugging Face",
      resourceId: "nvidia/segformer-b0-finetuned-ade-512-512",
    },
    ...over,
  });
}
