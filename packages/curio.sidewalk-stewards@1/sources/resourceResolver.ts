/** Package-local access to Curio's existing artifact and file endpoints. */
function backendUrl(): string {
  return (typeof window !== 'undefined' && (window as any).curio?.backendUrl) || 'http://localhost:5002';
}

function authHeaders(): Record<string, string> {
  if (typeof document === 'undefined') return {};
  const match = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return match ? { Authorization: `Bearer ${decodeURIComponent(match[1])}` } : {};
}

export async function fetchData(reference: string, signal?: AbortSignal): Promise<any> {
  const response = await fetch(`${backendUrl()}/get?fileName=${encodeURIComponent(reference)}`, { headers: authHeaders(), signal });
  if (!response.ok) throw new Error(`Could not read upstream spatial data (HTTP ${response.status}).`);
  return response.json();
}

export function assetUrl(path: string): string {
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  return `${backendUrl()}/file/${path.replace(/^\/+/, '')}`;
}
