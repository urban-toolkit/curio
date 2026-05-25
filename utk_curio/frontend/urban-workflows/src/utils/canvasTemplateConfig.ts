import { SupportedType } from "../constants";
import type { PortDraft, Category, Engine, Editor, TemplateDraft } from "../pages/nodes/factoryDraftModel";
import { factoryUiMakeId } from "../pages/nodes/factoryDraftModel";
import type { NodeDescriptor } from "../registry/types";
import { canvasTemplateLabelFromNode } from "./palettePackageFactoryDraft";

/** Per-canvas-node kind configuration (palette edit / Save As). */
export interface CanvasTemplateConfig {
  label: string;
  category: Category;
  engine: Engine;
  editor: Editor;
  description: string;
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  hasProvenance: boolean;
  hasExplanation: boolean;
  inputPorts: PortDraft[];
  outputPorts: PortDraft[];
  sourceFilename: string;
  sourceCode: string;
}

function portDefToDraft(
  ports: NodeDescriptor["inputPorts"],
): PortDraft[] {
  if (!ports.length) return [];
  return ports.map((p) => ({
    id: factoryUiMakeId(),
    types: p.types.join(","),
    cardinality: String(p.cardinality ?? "1"),
  }));
}

function defaultSourceFilename(desc: NodeDescriptor): string {
  const path = desc.package?.source;
  if (!path) return "default.py";
  const last = path.split("/").pop() ?? "";
  return last || "default.py";
}

export function canvasTemplateConfigFromDescriptor(
  desc: NodeDescriptor,
  node: { id: string; data: object },
  templateCode = ""
): CanvasTemplateConfig {
  const stored = readCanvasTemplateConfig(node);
  const label = canvasTemplateLabelFromNode(node, desc);
  const hasCode = desc.hasCode;
  const hasGrammar = desc.hasGrammar;
  const base: CanvasTemplateConfig = {
    label,
    category: desc.category as Category,
    engine: desc.editor === "grammar" ? "javascript" : "python",
    editor: desc.editor,
    description: desc.description ?? "",
    hasCode,
    hasWidgets: desc.hasWidgets,
    hasGrammar,
    hasProvenance: desc.hasProvenance ?? true,
    hasExplanation: hasCode || hasGrammar,
    inputPorts: portDefToDraft(desc.inputPorts),
    outputPorts:
      desc.outputPorts.length > 0
        ? portDefToDraft(desc.outputPorts)
        : [{ id: factoryUiMakeId(), types: SupportedType.JSON, cardinality: "1" }],
    sourceFilename: defaultSourceFilename(desc),
    sourceCode: templateCode,
  };
  if (!stored) return base;
  return {
    ...base,
    ...stored,
    label: stored.label?.trim() || base.label,
    inputPorts: stored.inputPorts?.length ? stored.inputPorts : base.inputPorts,
    outputPorts: stored.outputPorts?.length ? stored.outputPorts : base.outputPorts,
  };
}

export function readCanvasTemplateConfig(node: { data: object }): Partial<CanvasTemplateConfig> | null {
  const raw = (node.data as { packageTemplateConfig?: unknown })?.packageTemplateConfig;
  if (!raw || typeof raw !== "object") return null;
  return raw as Partial<CanvasTemplateConfig>;
}

export function applyCanvasTemplateConfigToTemplateDraft(
  draft: TemplateDraft,
  config: CanvasTemplateConfig | Partial<CanvasTemplateConfig> | null,
  labelOverride?: string,
): TemplateDraft {
  if (!config) {
    if (labelOverride?.trim()) return { ...draft, label: labelOverride.trim() };
    return draft;
  }
  const sourceFilename = config.sourceFilename?.trim() || draft.sourceFilename;
  return {
    ...draft,
    label: labelOverride?.trim() || config.label?.trim() || draft.label,
    category: (config.category as Category) ?? draft.category,
    engine: (config.engine as Engine) ?? draft.engine,
    editor: (config.editor as Editor) ?? draft.editor,
    description: config.description ?? draft.description,
    hasCode: config.hasCode ?? draft.hasCode,
    hasWidgets: config.hasWidgets ?? draft.hasWidgets,
    hasGrammar: config.hasGrammar ?? draft.hasGrammar,
    inputPorts: config.inputPorts?.length ? config.inputPorts : draft.inputPorts,
    outputPorts: config.outputPorts?.length ? config.outputPorts : draft.outputPorts,
    sourceFilename,
    sourceCode:
      typeof config.sourceCode === "string" && config.sourceCode.trim()
        ? config.sourceCode
        : draft.sourceCode,
  };
}

export function resolveEditorTabFlags(
  desc: NodeDescriptor,
  config: Partial<CanvasTemplateConfig> | null | undefined,
): {
  code: boolean;
  grammar: boolean;
  widgets: boolean;
  provenance: boolean;
  explanation: boolean;
} {
  const code = config?.hasCode ?? desc.hasCode;
  const grammar = config?.hasGrammar ?? desc.hasGrammar;
  const widgets = config?.hasWidgets ?? desc.hasWidgets;
  return {
    code,
    grammar,
    widgets,
    provenance: config?.hasProvenance ?? desc.hasProvenance ?? true,
    explanation: config?.hasExplanation ?? (code || grammar),
  };
}
