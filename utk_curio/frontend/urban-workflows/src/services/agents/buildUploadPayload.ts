/**
 * Assemble the upload-import payload (memo dev/36) from picked files:
 * exactly one `manifest.json` plus any number of `.txt` prompt files, which
 * become `prompts/<name>`. Pure and synchronous over already-read text so the
 * modal stays trivially testable; all real validation is server-side.
 */
export interface NamedText {
  name: string;
  text: string;
}

export interface UploadPayload {
  manifest: Record<string, unknown>;
  prompts: Record<string, string>;
}

export function buildUploadPayload(files: NamedText[]): UploadPayload {
  // A single exported bundle: `{manifest, prompts}` in one `.curio-agent.json`,
  // which is what "Export" on an agent's details screen produces. The loose
  // manifest.json + prompts/*.txt form below stays supported, but it needs two
  // directories in one file dialog and is the awkward half of this flow.
  const bundle = files.find((f) => f.name.toLowerCase().endsWith(".curio-agent.json"));
  if (bundle) {
    if (files.length > 1) {
      throw new Error("Pick the exported agent file on its own");
    }
    let parsed: { manifest?: unknown; prompts?: unknown };
    try {
      parsed = JSON.parse(bundle.text) as { manifest?: unknown; prompts?: unknown };
    } catch {
      throw new Error(`${bundle.name} is not valid JSON`);
    }
    if (!parsed.manifest || typeof parsed.manifest !== "object") {
      throw new Error(`${bundle.name} has no manifest`);
    }
    const prompts: Record<string, string> = {};
    for (const [rel, text] of Object.entries(
      (parsed.prompts as Record<string, unknown>) ?? {},
    )) {
      if (typeof text === "string") prompts[rel] = text;
    }
    return { manifest: parsed.manifest as Record<string, unknown>, prompts };
  }

  const manifests = files.filter((f) => f.name.toLowerCase() === "manifest.json");
  if (manifests.length !== 1) {
    throw new Error("Pick exactly one manifest.json");
  }
  let manifest: Record<string, unknown>;
  try {
    manifest = JSON.parse(manifests[0].text) as Record<string, unknown>;
  } catch {
    throw new Error("manifest.json is not valid JSON");
  }
  const prompts: Record<string, string> = {};
  for (const f of files) {
    if (f === manifests[0]) continue;
    if (!f.name.toLowerCase().endsWith(".txt")) {
      throw new Error(`Unsupported file ${f.name} — pick manifest.json and .txt prompts`);
    }
    prompts[`prompts/${f.name}`] = f.text;
  }
  return { manifest, prompts };
}
