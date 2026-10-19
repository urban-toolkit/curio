/** Published-library fixture, not a GPU/browser test or a package adaptation.
 * Internal coordinator access is test-only. No library source/prototype is patched.
 */
// No database operations occur in these event-only tests.
jest.mock('@urban-toolkit/autk-db', () => ({ AutkDb: class {} }), { virtual: true });
const nativeMap = jest.requireActual('@urban-toolkit/autk-map');
const nativeGrammar = jest.requireActual('@urban-toolkit/autk-grammar');

async function nativePick(highlighted: number[], hit: number) {
  const map = new nativeMap.AutkMap(document.createElement('canvas'), false);
  const emitted: any[] = [];
  map.events.on(nativeMap.MapEvent.PICKING, (event: any) => emitted.push(event));
  const ids = new Set(highlighted);
  const layer = { layerInfo: { id: 'input_0' }, clearHighlightedIds: () => ids.clear() };
  const pickableLayer = {
    get highlightedIds() { return [...ids]; },
    toggleHighlightedIds: (hits: number[]) => hits.forEach(id => ids.has(id) ? ids.delete(id) : ids.add(id)),
  };
  const read = jest.spyOn(map.renderer, 'readPickingResults').mockResolvedValue([hit]);
  try {
    map._picking.resolvePickingReadback({ layer, pickableLayer }, 0);
    await Promise.resolve();
    expect(read).toHaveBeenCalledWith(0, 1);
    expect(emitted).toHaveLength(1);
    return emitted[0];
  } finally { read.mockRestore(); }
}

test('different actual hit IDs collapse to the same native post-toggle payload', async () => {
  // A PCP highlight can set either starting state without a new map-picking event.
  const clickedFirst = await nativePick([0, 1], 0);
  const clickedThird = await nativePick([1, 2], 2);
  expect(clickedFirst).toEqual({ selection: [1], layerId: 'input_0' });
  expect(clickedThird).toEqual(clickedFirst);
  expect(clickedFirst).not.toHaveProperty('pickedIndex');
});

test('repeated hit toggles off; its payload is indistinguishable from a background miss', async () => {
  expect(await nativePick([], 1)).toEqual({ selection: [1], layerId: 'input_0' });
  const repeatedHit = await nativePick([1], 1);
  const backgroundMiss = await nativePick([1], -1);
  expect(repeatedHit).toEqual({ selection: [], layerId: 'input_0' });
  expect(backgroundMiss).toEqual(repeatedHit);
});

test('published grammar forwarding retains only layer and selection from a map event', () => {
  const map = new nativeMap.AutkMap(document.createElement('canvas'), false);
  const grammar = new nativeGrammar.AutkGrammar({});
  const emitted: any[] = [];
  grammar.interactions.on('map:picking', (event: any) => emitted.push(event));
  grammar._mapRegistry.set('input_0', map);
  grammar._rewireInteractions();
  // Diagnostic only: even if a future map emitted hit metadata, current grammar drops it.
  map.events.emit(nativeMap.MapEvent.PICKING, { selection: [1], layerId: 'input_0', pickedIndex: 0 });
  expect(emitted).toEqual([{ selection: [1], layerId: 'input_0' }]);
});
