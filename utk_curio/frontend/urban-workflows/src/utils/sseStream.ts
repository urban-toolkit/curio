/**
 * The agents SSE transport (memo dev/22; shared by the chat, Solve, simulation and job
 * streams — dev/63, dev/115). Split out of `api/agentsApi.ts` (memo dev/142, F1).
 */

import { getToken } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";

const BACKEND_URL = backendUrl();

/**
 * POST to an SSE endpoint and dispatch each parsed event frame (the dev/22
 * transport, shared by the chat and Solve streams — dev/63). Pre-stream
 * failures (404, 400, …) throw an Error carrying `status`/`body` like
 * `apiFetch`; frame payloads are JSON-decoded before dispatch.
 */
export async function postSseStream(
  path: string,
  body: unknown,
  onFrame: (event: string, payload: Record<string, unknown>) => void,
  signal?: AbortSignal,
  /** dev/115: the jobs re-attach stream is a GET (no body). */
  method: "POST" | "GET" = "POST"
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (method === "POST") headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method,
    headers,
    ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
    signal,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}) as Record<string, unknown>);
    const err = new Error((errBody as { error?: string }).error || `HTTP ${res.status}`);
    (err as Error & { status?: number; body?: unknown }).status = res.status;
    (err as Error & { status?: number; body?: unknown }).body = errBody;
    throw err;
  }
  if (!res.body) throw new Error("streaming not supported");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handleFrame = (frame: string) => {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!data) return;
    onFrame(event, JSON.parse(data) as Record<string, unknown>);
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      handleFrame(frame);
      sep = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) handleFrame(buffer);
}
