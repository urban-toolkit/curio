"""Rebuild the small, original CC0 Sidewalk example assets (Pillow, rasterio)."""
from pathlib import Path
import hashlib
import json


def main():
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from PIL import Image, ImageDraw

    root = Path(__file__).resolve().parents[1] / 'docs/examples/data/sidewalk-synthetic'
    (root / 'tiles').mkdir(parents=True, exist_ok=True)
    bounds = [-0.003, -0.002, 0, 0]
    grid, boundaries = [], []
    mosaic = Image.new('RGB', (384, 256))
    for row in range(2):
        for col in range(3):
            name = f'{col}_{row}'
            west, south = bounds[0] + col * .001, bounds[1] + row * .001
            ring = [[west, south], [west + .001, south], [west + .001, south + .001], [west, south + .001], [west, south]]
            props = {'tile_id': name, 'image_available': True, 'n_uncertain': col + row, 'Segments': 2}
            for i, field in enumerate(['Plaza', 'Walkway', 'Meander', 'Fragmented', 'Roadway', 'Vegetation', 'Road Mark', 'Uncertain']):
                props[field] = (1 + col + row) * (i + 1)
            grid.append({'type': 'Feature', 'id': name, 'properties': props,
                         'geometry': {'type': 'Polygon', 'coordinates': [ring]}})
            boundaries.append({'type': 'Feature', 'id': name, 'properties': {'tile_id': name},
                               'geometry': {'type': 'LineString', 'coordinates': ring}})
            image = Image.new('RGB', (128, 128), (225, 230, 218))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 52, 128, 76), fill=(180, 180, 180))
            draw.rectangle((52, 0, 76, 128), fill=(180, 180, 180))
            draw.text((5, 5), 'SYNTHETIC ' + name, fill=(30, 30, 30))
            image.save(root / 'tiles' / f'{name}.png')
            mosaic.paste(image, (col * 128, (1 - row) * 128))
    network = [{'type': 'Feature', 'id': f'edge-{row}', 'properties': {'source': 'original synthetic fixture'},
                'geometry': {'type': 'LineString', 'coordinates': [[-.0029, -.0015 + row * .001], [-.0001, -.0015 + row * .001]]}}
               for row in range(2)]
    for name, features in [('tile-grid', grid), ('tile-boundaries', boundaries), ('overview-network', network)]:
        (root / f'{name}.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, indent=2) + '\n')
    (root / 'tile-measurements.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': grid[::2]}, indent=2) + '\n')
    pixels = np.asarray(mosaic).transpose(2, 0, 1)
    with rasterio.open(root / 'synthetic.tif', 'w', driver='GTiff', width=384, height=256,
                       count=3, dtype='uint8', crs='EPSG:4326', transform=from_bounds(*bounds, 384, 256), compress='deflate') as out:
        out.write(pixels)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (root / 'mosaic-provenance.json').write_text(json.dumps({'mosaic': {'sha256': sha(root / 'synthetic.tif'),
        'crs': 'EPSG:4326', 'bounds': bounds, 'mapping': 'north-up, rectangular 3 by 2 grid'},
        'gridSha256': sha(root / 'tile-grid.geojson')}, indent=2) + '\n')
    (root / 'README.md').write_text('# Synthetic Sidewalk fixture\n\nOriginal schematic images and geometry, dedicated to CC0-1.0. No provider imagery or Recife measurements. Six tiles in EPSG:4326, two boundary-crossing lines. Rebuild with scripts/build_example_sidewalk_inspection.py.\n')


if __name__ == '__main__':
    main()
