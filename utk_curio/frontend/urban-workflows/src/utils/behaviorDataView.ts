/**
 * dev/90 A15 — the render-time data view handed to behavior hooks.
 *
 * The canonical fields are `data.code` (the node's persisted content) and
 * `data.appearance` — but generated behaviors in the wild also read
 * `data.content` (our own preview fixtures taught that spelling). One value,
 * two legal spellings: the runtime accepts both (the A14 lesson), computed
 * per render and never persisted.
 */
export function behaviorDataView<T extends { code?: unknown; content?: unknown }>(
  data: T,
): T & { content?: unknown } {
  if (!data || data.content !== undefined) return data;
  return { ...data, content: data.code };
}
