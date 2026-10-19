import type { Position } from './geojson';
import type { Wgs84Polygon } from './streetViewContract';
import { distanceMeters, pointInPolygon } from './streetViewImages';

/** Nearest geographic boundary point and true distance for an off-tile camera. */
export function cameraBoundary(point: Position, polygon: Wgs84Polygon): { nearest: Position; metres: number } | null {
  if (pointInPolygon(point, polygon)) return null;
  const latitude = point[1] * Math.PI / 180;
  const xScale = 111320 * Math.max(0.01, Math.cos(latitude));
  const yScale = 111320;
  let best: Position | null = null;
  let bestDistance = Infinity;
  for (const ring of polygon.coordinates) {
    for (let index = 0; index < ring.length; index += 1) {
      const a = ring[index]; const b = ring[(index + 1) % ring.length];
      const dx = (b[0] - a[0]) * xScale; const dy = (b[1] - a[1]) * yScale;
      const px = (point[0] - a[0]) * xScale; const py = (point[1] - a[1]) * yScale;
      const factor = Math.max(0, Math.min(1, (px * dx + py * dy) / (dx * dx + dy * dy || 1)));
      const candidate: Position = [a[0] + (b[0] - a[0]) * factor, a[1] + (b[1] - a[1]) * factor];
      const metres = distanceMeters(point, candidate);
      if (metres < bestDistance) { best = candidate; bestDistance = metres; }
    }
  }
  return best ? { nearest: best, metres: bestDistance } : null;
}
