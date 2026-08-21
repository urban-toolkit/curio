import { DatasetSchemaField } from "../../../services/datasetCatalog";

export type FieldIconKind = "geometry" | "integer" | "string" | "float" | "boolean";

export function normalizeFieldType(type: string): string {
  return type.trim().toUpperCase();
}

export function fieldIconKind(type: string): FieldIconKind {
  const normalized = normalizeFieldType(type);
  if (normalized.includes("GEOM")) return "geometry";
  if (normalized.includes("BOOL")) return "boolean";
  if (normalized.includes("INT")) return "integer";
  if (
    normalized.includes("FLOAT")
    || normalized.includes("DOUBLE")
    || normalized.includes("NUMBER")
    || normalized.includes("DECIMAL")
  ) {
    return "float";
  }
  return "string";
}

export function fieldIconGlyph(kind: FieldIconKind): string {
  switch (kind) {
    case "geometry":
      return "G";
    case "integer":
      return "#";
    case "boolean":
      return "b";
    case "float":
      return "~";
    default:
      return "T";
  }
}

export function isPrimaryKeyField(field: DatasetSchemaField, index: number, fields: DatasetSchemaField[]): boolean {
  const type = normalizeFieldType(field.type);
  if (!type.includes("INT")) return false;
  const name = field.name.toLowerCase();
  if (name === "id" || name.endsWith("_id")) {
    const firstPkIndex = fields.findIndex((candidate) => {
      const candidateType = normalizeFieldType(candidate.type);
      const candidateName = candidate.name.toLowerCase();
      return candidateType.includes("INT") && (candidateName === "id" || candidateName.endsWith("_id"));
    });
    return firstPkIndex === index;
  }
  return false;
}

export function schemaStats(fields: DatasetSchemaField[], geometryType?: string | null) {
  const nullableCount = fields.filter((field) => field.nullable).length;
  const geometryCount = fields.filter((field) => fieldIconKind(field.type) === "geometry").length
    || (geometryType ? 1 : 0);
  return {
    fieldCount: fields.length,
    nullableCount,
    geometryCount: geometryCount > 0 ? geometryCount : 0,
  };
}
