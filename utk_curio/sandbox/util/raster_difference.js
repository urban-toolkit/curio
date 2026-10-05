// The Autark half of a Compare Scenarios node's Difference of two rasters
// (#662), run in the sandbox's Node process as an Autark data section is:
// js_wrapper.mjs wraps it, so this is the body of the function it calls with
// `arg`, the request scenario_difference.py made: each raster's GeoTIFF bytes
// (base64), its label and the description the raster route serves beside its
// bytes.
//
// Both rasters are loaded by autk-db's loadGeoTiff with the parameters an
// Autark map loads a raster with (utils/raster/rasterLoad.ts: its own size,
// nearest, its EPSG CRS), exported with getRaster, and handed back as the
// envelopes a raster travels in between nodes (utils/raster/rasterWire.ts).
// Curio's raster algebra (util/raster_algebra.py) subtracts them. A raster
// an Autark map would refuse is refused here, in that sentence, by throwing.
import { AutkDb } from '@urban-toolkit/autk-db';
import { planForMeta } from '__CURIO_RASTER_MODULES__/rasterLoad.ts';
import { encodeRasterEnvelope, withGrid } from '__CURIO_RASTER_MODULES__/rasterWire.ts';

const db = new AutkDb();
await db.init();
const envelopes = {};
for (const role of ['reference', 'comparison']) {
  const side = arg[role];
  const plan = planForMeta(side.label, side.meta);
  if ('refused' in plan) throw new Error(plan.refused);
  const bytes = Buffer.from(side.geotiff, 'base64');
  await db.loadGeoTiff({
    geotiffArrayBuffer: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    outputTableName: role,
    ...plan.load,
  });
  envelopes[role] = encodeRasterEnvelope(withGrid(await db.getRaster(role), plan.grid));
}
return envelopes;
