import React from 'react';
import { act, fireEvent, render, waitFor } from '@testing-library/react';

import { DiscoverySourceIcon } from '../../pages/discovery/DiscoverySourceIcon';

jest.mock('../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../utils/authApi', () => ({ getToken: () => 'tok-123' }));

/**
 * The icon-or-glyph decision, which lives in one component precisely so it
 * cannot be implemented three ways.
 *
 * The icon route answers relative to the BACKEND and needs the bearer token
 * (#431). A bare `<img src>` resolves against the web app's origin and cannot
 * send a header, so the mark is fetched with the token and shown through an
 * object URL. A source that NAMES an icon whose file is gone, or one the route
 * refuses, must show a mark rather than a broken-image box.
 */
const ICON = '/api/discovery/sources/source.a.b@1/icon';

let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest
    .fn()
    .mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })) });
  (global as any).fetch = fetchMock;
  (global as any).URL.createObjectURL = jest.fn(() => 'blob:icon-1');
  (global as any).URL.revokeObjectURL = jest.fn();
});

const renderIcon = async (iconUrl: string | null) => {
  let view: ReturnType<typeof render>;
  await act(async () => {
    view = render(<DiscoverySourceIcon iconUrl={iconUrl} name="Alpha" />);
  });
  return view!;
};

describe('DiscoverySourceIcon', () => {
  test('fetches the portal mark from the backend with the token, and shows it', async () => {
    const { container } = await renderIcon(ICON);
    expect(fetchMock).toHaveBeenCalledWith(`http://backend.test${ICON}`, {
      headers: { Authorization: 'Bearer tok-123' },
      signal: expect.any(AbortSignal),
    });
    await waitFor(() => expect(container.querySelector('img')).not.toBeNull());
    expect(container.querySelector('img')!.getAttribute('src')).toBe('blob:icon-1');
  });

  test('renders the shared source glyph when there is none, and fetches nothing', async () => {
    const { container } = await renderIcon(null);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('falls back to the glyph when the route refuses the icon', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 });
    const { container } = await renderIcon(ICON);
    await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
    expect(container.querySelector('img')).toBeNull();
  });

  test('falls back to the glyph when the image fails to decode', async () => {
    const { container } = await renderIcon(ICON);
    await waitFor(() => expect(container.querySelector('img')).not.toBeNull());
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  test('the mark is decorative, because the name is always beside it', async () => {
    const { container } = await renderIcon(ICON);
    await waitFor(() => expect(container.querySelector('img')).not.toBeNull());
    const img = container.querySelector('img')!;
    expect(img.getAttribute('alt')).toBe('');
    expect(img.getAttribute('aria-hidden')).toBe('true');
  });

  test('the name is still available as a title on both renderings', async () => {
    const withIcon = await renderIcon(ICON);
    await waitFor(() => expect(withIcon.container.querySelector('img')).not.toBeNull());
    expect(withIcon.container.querySelector('[title="Alpha"]')).not.toBeNull();
    const without = await renderIcon(null);
    expect(without.container.querySelector('[title="Alpha"]')).not.toBeNull();
  });
});
