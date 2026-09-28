import {
  notableLegs,
  partialFailureMessage,
  scanningMessage,
  type LakeSearchLeg,
} from '../../services/dataLakeCatalog';

const leg = (sourceId: string, status: LakeSearchLeg['status']): LakeSearchLeg => ({
  sourceId,
  status,
});

describe('which legs are worth telling the user about', () => {
  test('a working portal is not news', () => {
    expect(notableLegs([leg('a', 'ok'), leg('b', 'ok')])).toEqual([]);
  });

  test('a link-only source is not news either', () => {
    // It reports `unsupported` on every single search. Surfacing that would
    // train people to ignore the line that also carries real failures.
    expect(notableLegs([leg('a', 'ok'), leg('direct', 'unsupported')])).toEqual([]);
  });

  test.each(['failed', 'refused', 'rate-limited', 'needs-token'] as const)(
    'a %s leg is',
    (status) => {
      expect(notableLegs([leg('a', 'ok'), leg('b', status)])).toHaveLength(1);
    }
  );

  test('a storage source being scanned did not fail to answer', () => {
    expect(notableLegs([leg('a', 'ok'), leg('s', 'scanning')])).toEqual([]);
  });
});

describe('scanningMessage', () => {
  const nameOf = (id: string) => ({ s: 'Example storage', t: 'Survey archive' }[id] ?? '');

  test('is null when no source is being scanned', () => {
    expect(scanningMessage([leg('s', 'ok'), leg('b', 'failed')], nameOf)).toBeNull();
  });

  test('says which sources are still being scanned', () => {
    expect(scanningMessage([leg('s', 'scanning')], nameOf)).toBe(
      'Example storage is still being scanned; its rows appear here when it is done.',
    );
    expect(scanningMessage([leg('s', 'scanning'), leg('t', 'scanning')], nameOf)).toBe(
      'Example storage and Survey archive are still being scanned; their rows appear here when they are done.',
    );
  });
});

describe('partialFailureMessage', () => {
  const nameOf = (id: string) => ({ a: 'Alpha Portal', b: 'Beta Portal' }[id] ?? '');

  test('is null when every portal answered', () => {
    expect(partialFailureMessage([leg('a', 'ok')], nameOf)).toBeNull();
  });

  test('names the one that did not, and says the rest are shown', () => {
    const msg = partialFailureMessage([leg('a', 'ok'), leg('b', 'failed')], nameOf);
    expect(msg).toContain('Beta Portal');
    expect(msg).toContain('Showing what the other portals returned');
  });

  test('reads as a list when several did not', () => {
    const msg = partialFailureMessage(
      [leg('a', 'failed'), leg('b', 'rate-limited')],
      nameOf
    );
    expect(msg).toContain('Alpha Portal and Beta Portal');
  });

  test('falls back to the id when the roster has no name for it', () => {
    // The roster and a search can disagree for a moment after an operator edit;
    // an id is ugly but true, and better than "undefined did not answer".
    expect(partialFailureMessage([leg('unknown.id', 'failed')], nameOf)).toContain(
      'unknown.id'
    );
  });
});
