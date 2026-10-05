// The raster half of a Compare Scenarios node's Difference (#662), run in the
// sandbox's Node process as an Autark data section is: js_wrapper.mjs wraps
// it, so this is the body of the function it calls with `arg`, the request
// scenario_difference.py made: each raster's GeoTIFF bytes (base64), its
// label and the description the raster route serves beside its bytes.
//
// Both rasters are loaded by autk-db's loadGeoTiff with the parameters an
// Autark map loads a raster with (utils/raster/rasterLoad.ts: its own size,
// nearest, its EPSG CRS), exported with getRaster, and subtracted by Curio's
// Autark adapter (utils/raster/rasterArithmetic.ts), comparison minus
// reference. The result is the envelope a raster travels in between nodes
// (utils/raster/rasterWire.ts). A refusal is thrown, in the sentence that
// names both rasters.
import { AutkDb } from '@urban-toolkit/autk-db';
import { planForMeta } from '__CURIO_RASTER_MODULES__/rasterLoad.ts';
import { encodeRasterEnvelope, withGrid } from '__CURIO_RASTER_MODULES__/rasterWire.ts';
import { subtractRasters } from '__CURIO_RASTER_MODULES__/rasterArithmetic.ts';

const db = new AutkDb();
await db.init();
const sides = [];
for (const [table, side] of [['reference', arg.reference], ['comparison', arg.comparison]]) {
  const plan = planForMeta(side.label, side.meta);
  if ('refused' in plan) throw new Error(plan.refused);
  const bytes = Buffer.from(side.geotiff, 'base64');
  await db.loadGeoTiff({
    geotiffArrayBuffer: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    outputTableName: table,
    ...plan.load,
  });
  sides.push({ name: side.label, collection: withGrid(await db.getRaster(table), plan.grid) });
}
const result = subtractRasters(sides[0], sides[1]);
if ('refused' in result) throw new Error(result.refused);
return encodeRasterEnvelope(result.collection);
