import { Node } from "reactflow";
import { AccessLevelType } from "../constants";
import { IInteraction, IPropagation } from "../providers/FlowProvider";
import { PythonInterpreter } from "../PythonInterpreter";

/**
 * Represents the content structure of code data
 */
export interface ICodeDataContent {
  dataType: string;
  data: any;
  metadata?: any;
}

/**
 * Represents code with its associated content
 */
export interface ICodeData {
  code: string;
  content: ICodeDataContent | string;
}

/**
 * Represents the data structure for a workflow node
 */
export interface INodeData {
  nodeId: string;
  input?: string;
  defaultCode?: string;
  pythonInterpreter?: PythonInterpreter;
  outputCallback?: (nodeId: string, output: string) => void;
  codeChangeCallback?: (nodeId: string, output: string) => void;
  interactionsCallback?: (interactions: any, nodeId: string) => void;
  propagationCallback?: (propagation: IPropagation) => void;
  description?: string;
  source?: string;
  templateId?: string;
  templateName?: string;
  accessLevel?: AccessLevelType;
  hidden?: boolean;
  nodeType: string;
  customTemplate?: boolean;
  interactions?: IInteraction[];
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

