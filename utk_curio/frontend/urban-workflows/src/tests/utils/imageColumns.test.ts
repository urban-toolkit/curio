/**
 * The one rule for "which columns hold images" (#276).
 *
 * Simple View keyed on `input.data.image_id` - a DataFrame column map - so a
 * GeoDataFrame of image URLs, which is exactly what the street-vision pipeline
 * produces, fell through to a table. These cases pin the replacement rule,
 * including the two deliberate asymmetries between the recognized-name pass
 * and the sniffing pass.
 */
import {
  RECOGNIZED_COLUMNS,
  resolveImageColumns,
  resolveImageSource,
} from '../../utils/imageColumns';

const longBase64 = 'iVBORw0KGgo' + 'A'.repeat(80);

describe('resolveImageSource', () => {
  it('takes a data: URI straight to the DOM', () => {
    expect(resolveImageSource('data:image/png;base64,AAA')).toEqual({
      kind: 'direct',
      src: 'data:image/png;base64,AAA',
    });
  });

  it('routes a same-origin /api path through an authenticated fetch', () => {
    // The overlay route reads WHICH user is asking from the bearer token, so a
    // bare <img src> would resolve to the shared guest and 404.
    expect(resolveImageSource('/api/streetvision/inference/overlay/pano.jpg')).toEqual({
      kind: 'authed',
      path: '/api/streetvision/inference/overlay/pano.jpg',
    });
  });

  it('accepts an extensionless http URL when the column was named', () => {
    const url = 'https://maps.googleapis.com/maps/api/streetview?pano=CAoSL&size=640x640';
    expect(resolveImageSource(url)).toEqual({ kind: 'direct', src: url });
    // ...but not while sniffing an unnamed column.
    expect(resolveImageSource(url, { requireExtension: true })).toBeNull();
  });

  it('prefixes bare base64, the historical image_content contract', () => {
    expect(resolveImageSource(longBase64)).toEqual({
      kind: 'direct',
      src: `data:image/png;base64,${longBase64}`,
    });
    expect(resolveImageSource(longBase64, { allowBase64: false })).toBeNull();
  });

  it('rejects short strings, non-strings and blanks', () => {
    expect(resolveImageSource('vegetation')).toBeNull();
    expect(resolveImageSource(42)).toBeNull();
    expect(resolveImageSource(null)).toBeNull();
    expect(resolveImageSource('   ')).toBeNull();
  });
});

describe('resolveImageColumns', () => {
  it('finds image_url in a GeoDataFrame-shaped row, the case that used to fail', () => {
    const rows = [
      { image_id: 'CAoSL1', image_url: 'https://example.test/a?size=640', vegetation: 31.2 },
      { image_id: 'CAoSL2', image_url: 'https://example.test/b?size=640', vegetation: 12.7 },
    ];
    expect(resolveImageColumns(rows)).toEqual(['image_url']);
  });

  it('keeps the Image.json contract working', () => {
    const rows = [
      { image_id: 0, image_content: longBase64 },
      { image_id: 1, image_content: longBase64 },
    ];
    expect(resolveImageColumns(rows)).toEqual(['image_content']);
  });

  it('returns every recognized column, in RECOGNIZED_COLUMNS order', () => {
    const rows = [
      {
        overlay_url: '/api/streetvision/inference/overlay/a.jpg',
        image_url: 'https://example.test/a?size=640',
        dominant_class: 'road',
      },
    ];
    // image_url is listed before overlay_url, so source comes before overlay.
    expect(resolveImageColumns(rows)).toEqual(['image_url', 'overlay_url']);
    expect(RECOGNIZED_COLUMNS.indexOf('image_url'))
      .toBeLessThan(RECOGNIZED_COLUMNS.indexOf('overlay_url'));
  });

  it('ignores a recognized name that does not actually hold images', () => {
    const rows = [{ image_url: 'not a url', label: 'road' }];
    expect(resolveImageColumns(rows)).toEqual([]);
  });

  it('sniffs an unrecognised column only when it carries real image URLs', () => {
    const rows = [
      { photo: 'https://example.test/a.png', note: 'leafy' },
      { photo: 'https://example.test/b.png', note: 'paved' },
    ];
    expect(resolveImageColumns(rows)).toEqual(['photo']);
  });

  it('does not mistake an id column for images while sniffing', () => {
    // Long, base64-shaped, and not an image. This is why bare base64 is only
    // honoured under a recognized column name.
    const rows = [{ checksum: longBase64 }, { checksum: longBase64 }];
    expect(resolveImageColumns(rows)).toEqual([]);
  });

  it('does not sniff an extensionless URL column', () => {
    const rows = [{ link: 'https://example.test/page?id=1' }];
    expect(resolveImageColumns(rows)).toEqual([]);
  });

  it('tolerates a mostly-populated column and an empty frame', () => {
    const rows = [
      { image_url: 'https://example.test/a?size=640' },
      { image_url: null },
      { image_url: 'https://example.test/b?size=640' },
    ];
    expect(resolveImageColumns(rows)).toEqual(['image_url']);
    expect(resolveImageColumns([])).toEqual([]);
  });
});
