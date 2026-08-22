/**
 * Extracts the Python package requirements for a Jupyter notebook by
 * sending its code cells to the backend for AST-based import analysis
 * and version resolution.
 *
 * @param notebook - parsed .ipynb JSON
 * @param backendUrl - base URL of the backend API
 * @returns list of requirement strings, e.g. ["pandas==2.1.4", "numpy==1.26.2"]
 * @throws if the backend request fails or returns a non-OK status
 */
export async function getNotebookRequirements(
  notebook: Record<string, unknown>,
  backendUrl: string
): Promise<string[]> {
  const res = await fetch(`${backendUrl}/api/extractRequirements`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notebook }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to extract requirements (${res.status}): ${text}`);
  }

  const data = (await res.json()) as { requirements: string[] };
  return data.requirements;
}