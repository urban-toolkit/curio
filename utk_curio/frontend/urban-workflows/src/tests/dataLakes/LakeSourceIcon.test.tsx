import React from 'react';
import { fireEvent, render } from '@testing-library/react';

import { LakeSourceIcon } from '../../pages/dataLakes/LakeSourceIcon';

/**
 * The icon-or-glyph decision, which lives in one component precisely so it
 * cannot be implemented three ways. The interesting case is the third one:
 * a source that NAMES an icon whose file is gone. The route 404s, the `<img>`
 * errors, and the grid must show a mark rather than a broken-image box.
 */
describe('LakeSourceIcon', () => {
  test('renders the portal mark when there is one', () => {
    const { container } = render(
      <LakeSourceIcon iconUrl="/api/datalakes/sources/lake.a.b@1/icon" name="Alpha" />
    );
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img!.getAttribute('src')).toBe('/api/datalakes/sources/lake.a.b@1/icon');
  });

  test('renders the shared lake glyph when there is none', () => {
    const { container } = render(<LakeSourceIcon iconUrl={null} name="Alpha" />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  test('falls back to the glyph when the image fails to load', () => {
    const { container } = render(
      <LakeSourceIcon iconUrl="/api/datalakes/sources/lake.a.b@1/icon" name="Alpha" />
    );
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  test('the mark is decorative, because the name is always beside it', () => {
    const { container } = render(
      <LakeSourceIcon iconUrl="/icon.png" name="Alpha" />
    );
    const img = container.querySelector('img')!;
    expect(img.getAttribute('alt')).toBe('');
    expect(img.getAttribute('aria-hidden')).toBe('true');
  });

  test('the name is still available as a title on both renderings', () => {
    const withIcon = render(<LakeSourceIcon iconUrl="/icon.png" name="Alpha" />);
    expect(withIcon.container.querySelector('[title="Alpha"]')).not.toBeNull();
    const without = render(<LakeSourceIcon iconUrl={null} name="Alpha" />);
    expect(without.container.querySelector('[title="Alpha"]')).not.toBeNull();
  });
});
