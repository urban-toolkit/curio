import { Node } from "reactflow";
import { AccessLevelType } from "../constants";
import { IInteraction, IPropagation } from "../providers/FlowProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { JavaScriptInterpreter } from "../JavaScriptInterpreter";

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
 * distribution name, is not stdlib, is not Curio's own, and nothing installed
 * already provides it. It does NOT mean the distribution exists on PyPI - the
 * backend deliberately does not ask, so the install is an attempt and pip's own
 * failure is what the user sees when the guess is wrong.
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
    | null;
  detail: string | null;
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
  outputCallback?: (nodeId: string, output: string) => void;
  codeChangeCallback?: (nodeId: string, output: string) => void;
  interactionsCallback?: (interactions: any, nodeId: string) => void;
  propagationCallback?: (propagation: IPropagation) => void;
  propagation?: any;
  description?: string;
  source?: string;
  templateId?: string;
  templateName?: string;
  accessLevel?: AccessLevelType;
  hidden?: boolean;
  nodeType: string;
  customTemplate?: boolean;
  interactions?: IInteraction[];
  triggerExec?: number;
}

/**
 * Represents a workflow node with extended properties
 */
export interface INode extends Node {
  id: string;
  type: string;
  // position: object;
  // width: string;
  // height: string;
  data: INodeData;
}

