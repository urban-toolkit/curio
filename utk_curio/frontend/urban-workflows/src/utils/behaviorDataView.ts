/**
 * dev/90 A15 — the render-time data view handed to behavior hooks.
 *
 * The canonical fields are `data.code` (the node's persisted content) and
 * `data.appearance` — but generated behaviors in the wild also read
 * `data.content` (our own preview fixtures taught that spelling). One value,
 * two legal spellings: the runtime accepts both (the A14 lesson), computed
 * per render and never persisted.
 *
 * A view over the node's data, not a copy: a behavior's own writes reach the
 * node, as `data.code` writes do elsewhere. A package template's widgets,
 * seeded beside its starter on a fresh drop (`packageNodeBehavior`), were
 * written to a copy and lost, so the node's references named no widget.
 * `content` is read from `code` and never written to the node.
 */
export function behaviorDataView<T extends { code?: unknown; content?: unknown }>(
  data: T,
): T & { content?: unknown } {
  if (!data || data.content !== undefined) return data;
  return new Proxy(data, {
    get(target, key, receiver) {
      return key === "content" ? target.code : Reflect.get(target, key, receiver);
    },
    has(target, key) {
      return key === "content" || Reflect.has(target, key);
    },
    set(target, key, value) {
      return key === "content" ? true : Reflect.set(target, key, value);
    },
  });
}
