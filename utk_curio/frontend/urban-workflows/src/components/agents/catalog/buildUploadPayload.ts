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
