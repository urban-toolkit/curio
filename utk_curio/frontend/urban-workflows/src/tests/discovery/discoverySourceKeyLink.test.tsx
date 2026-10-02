import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { discoverySourceAccessItems } from '../../pages/discovery/discoverySourceFacts';
import {
  CONNECTION_KEYS_EVENT,
  type ConnectionKeysFocus,
} from '../../components/connectionKeys/connectionKeysRequest';
import type { DiscoverySourceRow } from '../../services/discoveryCatalog';

/**
 * A source that sends a key says where to set it: its Access list opens API
 * Settings on that key's row, through the same request event the agent cards
 * use for connection keys.
 */

const gated = (present: boolean): DiscoverySourceRow =>
  ({
    sourceId: 'source.a.portal',
    dirName: 'source.a.portal@1',
    name: 'Alpha Portal',
    auth: {
      mode: 'optional-token', required: false, usesToken: true,
      secretId: 'socrata.app-token', present, helpUrl: null,
    },
  }) as unknown as DiscoverySourceRow;

function renderAccess(source: DiscoverySourceRow) {
  return render(<ul>{discoverySourceAccessItems(source)}</ul>);
}

describe("a source's key link", () => {
  test('asks API Settings for that key, and says Add when none is saved', () => {
    const seen: ConnectionKeysFocus[] = [];
    const listener = (event: Event) => seen.push((event as CustomEvent<ConnectionKeysFocus>).detail);
    window.addEventListener(CONNECTION_KEYS_EVENT, listener);
    try {
      renderAccess(gated(false));
      fireEvent.click(screen.getByRole('button', { name: 'Add yours in API Settings' }));
    } finally {
      window.removeEventListener(CONNECTION_KEYS_EVENT, listener);
    }
    expect(seen).toEqual([{ section: 'source-key', slot: 'socrata.app-token' }]);
  });

  test('says Change when one is saved', () => {
    renderAccess(gated(true));
    expect(screen.getByRole('button', { name: 'Change it in API Settings' })).toBeInTheDocument();
  });

  test('a public source has no Access list, and so no link', () => {
    const open = {
      ...gated(false),
      auth: { mode: 'public', required: false, usesToken: false, secretId: null, present: false, helpUrl: null },
    } as unknown as DiscoverySourceRow;
    expect(discoverySourceAccessItems(open)).toEqual([]);
  });
});
