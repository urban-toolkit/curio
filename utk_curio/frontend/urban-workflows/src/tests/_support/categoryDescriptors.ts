/**
 * Node descriptors that carry only what a preview reads, a category, registered
 * as `packagesClient` registers a template: keyed `<packageId>/<templateId>@<major>`.
 * The categories of Curio's own templates are read from their shipped
 * manifests, so a suite checks the categories users see.
 */
import fs from "fs";
import path from "path";

import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import type { NodeCategory, NodeDescriptor } from "../../registry/types";

const PACKAGES = path.resolve(__dirname, "../../../../../../packages");

/** A shipped package's manifest. */
export function shippedManifest(dirName: string): {
  id: string;
  compatibility: { major: number };
  templates: Array<{ id: string; category: string }>;
} {
  return JSON.parse(fs.readFileSync(path.join(PACKAGES, dirName, "manifest.json"), "utf8"));
}

/** Every shipped package's manifest, by folder name. */
export function shippedManifests(): Record<string, ReturnType<typeof shippedManifest>> {
  const out: Record<string, ReturnType<typeof shippedManifest>> = {};
  for (const dirName of fs.readdirSync(PACKAGES).sort()) {
    if (fs.existsSync(path.join(PACKAGES, dirName, "manifest.json"))) out[dirName] = shippedManifest(dirName);
  }
  return out;
}

/** Registers a descriptor of *id* (`<packageId>/<templateId>@<major>`) in
 *  *category*, named *label* (its id unless given). */
export function registerCategoryDescriptor(id: string, category: NodeCategory, label: string = id): void {
  const [unversioned, major] = id.split("@");
  const packageId = unversioned.split("/")[0];
  registerNode({
    id,
    source: "package",
    package: { packageId, major: Number(major), version: "1.0.0", name: packageId, publisher: "Test" },
    category,
    label,
    icon: {},
    inputPorts: [],
    outputPorts: [],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
  } as unknown as NodeDescriptor);
}

/** Registers every template of the shipped package in *dirName* with the
 *  category its manifest declares; gives `{node type: category}`, unversioned. */
export function registerShippedTemplates(dirName: string): Record<string, NodeCategory> {
  const manifest = shippedManifest(dirName);
  const out: Record<string, NodeCategory> = {};
  for (const template of manifest.templates) {
    const type = `${manifest.id}/${template.id}`;
    registerCategoryDescriptor(`${type}@${manifest.compatibility.major}`, template.category as NodeCategory);
    out[type] = template.category as NodeCategory;
  }
  return out;
}

/** Drops every descriptor a suite registered but the built-in package's,
 *  which the registry keeps across refreshes. */
export function clearCategoryDescriptors(): void {
  clearPackageNodes();
}
