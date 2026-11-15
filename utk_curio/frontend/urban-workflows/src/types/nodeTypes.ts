import { AccessLevelType } from "../constants";
import { IInteraction, IPropagation } from "../providers/FlowProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { JavaScriptInterpreter } from "../JavaScriptInterpreter";
import type { SelectionEchoOptions } from "../utils/selectionEcho";

/**
 * Represents the content structure of code data
 */
export interface ICodeDataContent {
  dataType: string;
  data: any;
  metadata?: any;
  path?: string;
}

/**
 * Represents code with its associated content
 */
/**
 * A library a failed node run turned out to be missing (#299), as reported by
 * ``/processPythonCode``. Null on every run that did not end in a
 * ``ModuleNotFoundError``.
 *
 * ``installable`` is the whole decision: it means the name is a legal
 * distribution name, is not stdlib, is not Curio's own, is not a module a
 * package ships, and nothing installed already provides it. It does NOT mean
 * the distribution exists on PyPI - the backend deliberately does not ask, so
 * the install is an attempt and pip's own failure is what the user sees when
 * the guess is wrong.
 */
export interface MissingModuleNotice {
  module: string;
  distribution: string | null;
  installable: boolean;
  reason:
    | "stdlib"
    | "curio-provided"
    | "unsafe-name"
    | "installed-but-broken"
    | "installed-not-visible"
    // The instance does not allow installs, or this caller may not ask for one.
    | "install-disabled"
    // A module of a catalog package the account has not added: `package`.
    | "package-not-added"
    // A module of a package the account has, which only `nodes` import.
    | "package-module"
    | null;
  detail: string | null;
  /** The package that ships the module, for the two package reasons. */
  package?: MissingModulePackage | null;
  /** "package-module": the labels of the nodes that import the module. */
  nodes?: string[];
}

/** A package as a missing-module notice names it. */
export interface MissingModulePackage {
  /** The package's id, without its major. */
  id: string;
  /** "model" for a package of the Model Catalog, "node" for the Node Catalog's. */
  kind: "node" | "model";
  /** The name its catalog lists it by. */
  name: string;
}

export interface ICodeData {
  code: string;
  content: ICodeDataContent | string;
  outputType?: string;
  missingModule?: MissingModuleNotice | null;
}

/**
 * Represents the data structure for a workflow node
 */
export interface INodeData {
  nodeId: string;
  input?: any;
  defaultCode?: string;
  pythonInterpreter?: PythonInterpreter;
  jsInterpreter?: JavaScriptInterpreter;
  /** `options.selectionEcho`: the output is a selection coming back, not new data (see utils/selectionEcho). */
  outputCallback?: (nodeId: string, output: string, options?: SelectionEchoOptions) => void;
  codeChangeCallback?: (nodeId: string, output: string) => void;
  interactionsCallback?: (interactions: any, nodeId: string) => void;
  propagationCallback?: (propagation: IPropagation) => void;
  propagation?: any;
  description?: string;
  source?: string;
  /** A node with several input ports (the Spatial Join): what each port holds, by handle (FlowProvider). */
  portInputs?: Record<string, unknown>;
  templateId?: string;
  templateName?: string;
  accessLevel?: AccessLevelType;
  hidden?: boolean;
  nodeType: string;
  customTemplate?: boolean;
  interactions?: IInteraction[];
  triggerExec?: number;
  /** Bumped when a run does not run this node because a node feeding it failed. */
  skipExec?: number;
  /** What the node shows for that run in place of an outcome. */
  skipReason?: string;
}

