import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { discoverySourceAccessItems } from '../../pages/discovery/discoverySourceFacts';
import {
  API_SETTINGS_EVENT,
  type ApiSettingsFocus,
} from '../../components/apiSettings/apiSettingsRequest';
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
  return render(<ul>{discoverySourceAccessItems(source, false)}</ul>);
}

describe("a source's key link", () => {
  test('asks API Settings for that key, and says Add when none is saved', () => {
    const seen: ApiSettingsFocus[] = [];
    const listener = (event: Event) => seen.push((event as CustomEvent<ApiSettingsFocus>).detail);
    window.addEventListener(API_SETTINGS_EVENT, listener);
    try {
      renderAccess(gated(false));
      fireEvent.click(screen.getByRole('button', { name: 'Add yours in API Settings' }));
    } finally {
      window.removeEventListener(API_SETTINGS_EVENT, listener);
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
    expect(discoverySourceAccessItems(open, false)).toEqual([]);
  });
});
