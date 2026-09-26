import {
  LAKE_ACQUIRABLE_FORMATS,
  isSearchable,
  unsearchableReason,
  type LakeSourceRow,
} from '../../services/dataLakeCatalog';

function source(over: Partial<LakeSourceRow> = {}): LakeSourceRow {
  return {
    sourceId: 'lake.a.portal',
    dirName: 'lake.a.portal@1',
    name: 'Alpha Portal',
    version: '1.0.0',
    description: '',
    publisher: 'Alpha',
    homepage: null,
    license: '',
    tags: [],
    iconUrl: null,
    provider: 'ckan',
    baseUrl: 'https://alpha.example',
    auth: {
      mode: 'public',
      required: false,
      usesToken: false,
      secretId: null,
      present: false,
      helpUrl: null,
    },
    capabilities: {
      search: true,
      describe: true,
      download: true,
      formats: ['csv'],
      maxDownloadBytes: 1024,
    },
    createdAt: null,
    updatedAt: null,
    ...over,
  };
}

describe('isSearchable', () => {
  test('a public searchable portal is', () => {
    expect(isSearchable(source())).toBe(true);
    expect(unsearchableReason(source())).toBeNull();
  });

  test('a source with no search is not', () => {
    const s = source({ capabilities: { ...source().capabilities, search: false } });
    expect(isSearchable(s)).toBe(false);
    expect(unsearchableReason(s)).toMatch(/nothing to browse/);
  });

  test('a required token you do not hold blocks it', () => {
    // Narrower than capabilities.search alone. Offering a search box that is
    // guaranteed to 428 is worse than saying why up front.
    const s = source({
      auth: { ...source().auth, mode: 'required-token', required: true, usesToken: true, present: false },
    });
    expect(isSearchable(s)).toBe(false);
    expect(unsearchableReason(s)).toMatch(/needs a token/);
  });

  test('a required token you DO hold does not', () => {
    const s = source({
      auth: { ...source().auth, mode: 'required-token', required: true, usesToken: true, present: true },
    });
    expect(isSearchable(s)).toBe(true);
  });

  test('an optional token you lack does not block it', () => {
    const s = source({
      auth: { ...source().auth, mode: 'optional-token', required: false, usesToken: true, present: false },
    });
    expect(isSearchable(s)).toBe(true);
  });
});

describe('LAKE_ACQUIRABLE_FORMATS', () => {
  test('excludes the formats a portal cannot deliver as one file', () => {
    // shp needs its sibling .dbf/.shx; bundle is a node output, not a download.
    expect(LAKE_ACQUIRABLE_FORMATS).not.toContain('shp' as never);
    expect(LAKE_ACQUIRABLE_FORMATS).not.toContain('bundle' as never);
  });
});
