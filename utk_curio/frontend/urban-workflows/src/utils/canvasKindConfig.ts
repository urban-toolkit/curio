import { SupportedType } from "../constants";
import type { PortDraft, Category, Engine, Editor, KindDraft } from "../pages/nodes/factoryDraftModel";
import { factoryUiMakeId } from "../pages/nodes/factoryDraftModel";
import type { NodeDescriptor } from "../registry/types";
import { canvasKindLabelFromNode } from "./palettePackFactoryDraft";

/** Per-canvas-node kind configuration (palette edit / Save As). */
export interface CanvasKindConfig {
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
  defaultTemplateName: string;
  defaultTemplateCode: string;
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

function defaultTemplateFilename(desc: NodeDescriptor): string {
  const path = desc.pack?.defaultTemplate;
  if (!path) return "Default.py";
  const last = path.split("/").pop() ?? "";
  return last.endsWith(".py") || last.endsWith(".js") ? last : "Default.py";
}

export function canvasKindConfigFromDescriptor(
  desc: NodeDescriptor,
  node: { id: string; data: object },
  templateCode = ""
): CanvasKindConfig {
  const stored = readCanvasKindConfig(node);
  const label = canvasKindLabelFromNode(node, desc);
  const hasCode = desc.hasCode;
  const hasGrammar = desc.hasGrammar;
  const base: CanvasKindConfig = {
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
    defaultTemplateName: defaultTemplateFilename(desc),
    defaultTemplateCode: templateCode,
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

export function readCanvasKindConfig(node: { data: object }): Partial<CanvasKindConfig> | null {
  const raw = (node.data as { packKindConfig?: unknown })?.packKindConfig;
  if (!raw || typeof raw !== "object") return null;
  return raw as Partial<CanvasKindConfig>;
}

export function applyCanvasKindConfigToKindDraft(
  draft: KindDraft,
  config: CanvasKindConfig | Partial<CanvasKindConfig> | null,
  labelOverride?: string,
): KindDraft {
  if (!config) {
    if (labelOverride?.trim()) return { ...draft, label: labelOverride.trim() };
    return draft;
  }
  const kindId = draft.id;
  const templateDir = `templates/${kindId}`;
  const templateName = config.defaultTemplateName?.trim() || draft.defaultTemplateName;
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
    templateDir,
    defaultTemplateName: templateName,
    defaultTemplate: `${templateDir}/${templateName}`,
    defaultTemplateCode:
      typeof config.defaultTemplateCode === "string" && config.defaultTemplateCode.trim()
        ? config.defaultTemplateCode
        : draft.defaultTemplateCode,
  };
}

export function resolveEditorTabFlags(
  desc: NodeDescriptor,
  config: Partial<CanvasKindConfig> | null | undefined,
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
