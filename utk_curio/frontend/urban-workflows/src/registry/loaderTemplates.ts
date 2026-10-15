/**
 * Which templates are loaders: the nodes that start a dataflow by bringing data
 * in (plans/data-loading-expressive-preview-memo.md). They get the preview mode.
 *
 * One rule rather than a list, so a package loader added later is covered: the
 * built-in Data Loading, or any template in the data category whose content is
 * code and which takes no input. Data Transformation is a data code node too,
 * but it has an input, so it is not a loader.
 */
import { NodeType } from "../constants";
import { unversionedNodeType } from "../utils/flowNodeCanonicalType";
import type { NodeDescriptor } from "./types";

type LoaderShape = Pick<NodeDescriptor, "id" | "category" | "hasCode" | "hasGrammar" | "inputPorts">;

export function isLoaderTemplate(descriptor: LoaderShape | null | undefined): boolean {
  if (!descriptor) return false;
  if (unversionedNodeType(String(descriptor.id)) === NodeType.DATA_LOADING) return true;
  return (
    descriptor.category === "data" &&
    descriptor.hasCode &&
    !descriptor.hasGrammar &&
    (descriptor.inputPorts?.length ?? 0) === 0
  );
}

/**
 * The view a loader dropped from a palette starts in. The bare Data Loading
 * tool has no code yet, so it opens on the editor; a package's loader brings
 * its own code, so it opens on its preview.
 */
export function initialLoaderView(descriptor: LoaderShape | null | undefined): "preview" | "code" | undefined {
  if (!isLoaderTemplate(descriptor)) return undefined;
  return unversionedNodeType(String(descriptor!.id)) === NodeType.DATA_LOADING ? "code" : "preview";
}
