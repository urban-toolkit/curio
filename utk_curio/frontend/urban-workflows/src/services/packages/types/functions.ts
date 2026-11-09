/**
 * New node from a Python function: the functions installed packages' modules
 * define (`GET /api/packages/factory/functions`), and the template the backend
 * writes for one (`POST /api/packages/factory/function-template`).
 */

import type { WidgetDef } from "../../../utils/widgets/widgetModel";

/** What a parameter is given: a widget, a fixed value, one of the node's inputs, or its own default. */
export type FunctionParameterUse = "widget" | "fixed" | "input" | "default";

export interface FunctionParameterPayload {
  name: string;
  kind: "positional-only" | "positional-or-keyword" | "keyword-only";
  annotation: string | null;
  hasDefault: boolean;
  /** The default as the source writes it. */
  defaultText?: string;
  /** The widget the annotation or default suggests, or null. */
  widget: WidgetDef | null;
  /** What the dialog starts the parameter at. */
  use: FunctionParameterUse;
}

export interface FunctionPayload {
  name: string;
  doc: string;
  /** Why a node cannot call it (`*args`, `**kwargs`, async), or null. */
  problem: string | null;
  parameters: FunctionParameterPayload[];
}

export interface FunctionModulePayload {
  /** Dotted module name, as the template imports it. */
  module: string;
  /** Why the module could not be read (it does not parse), or null. */
  problem: string | null;
  functions: FunctionPayload[];
}

export interface FunctionPackagePayload {
  dirName: string;
  packageId: string;
  major: number;
  name: string;
  readOnly: boolean;
  modules: FunctionModulePayload[];
}

/** One parameter's binding, as the dialog sends it. */
export type FunctionParameterBinding =
  | { use: "widget"; widget: WidgetDef }
  | { use: "fixed"; value: string }
  | { use: "input" }
  | { use: "default" };

export interface FunctionTemplateRequest {
  dirName: string;
  module: string;
  function: string;
  label?: string;
  bindings: Record<string, FunctionParameterBinding>;
}

/**
 * A function a node's code can call, as the header above its code lists it
 * (`GET /api/packages/node-functions`), and a package's, as its details list
 * them (`GET /api/packages/<dirName>/functions`), which carry no `insert`.
 */
export interface OfferedFunctionPayload {
  name: string;
  /** Its signature: `season_factor(season)`. */
  call: string;
  /** The first paragraph of its docstring; for one of Curio's, what the page that lists them says it does. */
  doc: string;
  /** The call a click on it writes: the arguments a call must give. */
  insert?: string;
}

/** A module and the functions it offers: its `__all__`, else its public functions. */
export interface OfferedModulePayload {
  /** The `<packageId>@<major>` that ships it; left out of a package's own details. */
  package?: string;
  /** Dotted module name, as code imports it. */
  module: string;
  /** Why the module could not be read, or null. */
  problem: string | null;
  functions: OfferedFunctionPayload[];
}

/** What a node's code can call: Curio's functions for its engine, then, for a
 * Python node, those of the modules a run hands it, its own package's first. */
export interface NodeFunctionsPayload {
  /** The engine of the node's template; null for a node that holds no code. */
  engine: "python" | "javascript" | null;
  curio: OfferedFunctionPayload[];
  modules: OfferedModulePayload[];
}

/** Each module of a package with the functions it offers. */
export interface PackageFunctionsPayload {
  dirName: string;
  modules: OfferedModulePayload[];
}

/** The template a function becomes: a manifest entry and its source file. */
export interface FunctionTemplatePayload {
  template: {
    id: string;
    label: string;
    category: string;
    engine: "python";
    editor: "code";
    behavior: string;
    iconRef: string;
    description: string;
    hasCode: boolean;
    hasWidgets: boolean;
    hasGrammar: boolean;
    inputPorts: { types: string[]; cardinality: string }[];
    outputPorts: { types: string[]; cardinality: string }[];
    source: string;
    widgets?: WidgetDef[];
  };
  source: { filename: string; code: string };
  /** The function's package. */
  package: { dirName: string; packageId: string; major: number; readOnly: boolean };
  /** The `dependencies.packages` entry a template in another package needs. */
  dependency: Record<string, string>;
}
