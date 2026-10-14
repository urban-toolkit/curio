/**
 * The Note node of `curio.notes@1`: the post-it the Researcher writes into.
 *
 * Imported from `packages/`, as the Column Filter test does: the package's
 * source is what ships. A note draws its text as simple markdown, never as
 * HTML, takes its color from `appearance.backgroundColor`, and runs nothing.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { useNoteBehavior, noteColor, textColor } = require(
  '../../../../../../../packages/curio.notes@1/sources/noteBehavior',
);

function Note({ data }: { data: any }) {
  const behavior = useNoteBehavior(data, {} as any);
  return <>{behavior.contentComponent}</>;
}

describe('the Note node', () => {
  it('runs nothing and has no handles', () => {
    const behavior = useNoteBehavior({ code: 'x' } as any, {} as any);
    expect(behavior.disablePlay).toBe(true);
    expect(behavior.handlesOverride).toEqual([]);
  });

  it('takes a palette name or a hex color, and yellow otherwise', () => {
    expect(noteColor('green')).toBe('#d5f5d0');
    expect(noteColor('#123456')).toBe('#123456');
    expect(noteColor('red; background: url(x)')).toBe('#fff3b0');
    expect(noteColor(undefined)).toBe('#fff3b0');
  });

  it('writes dark text on a light note and light text on a dark one', () => {
    expect(textColor('#fff3b0')).toBe('#1e1f23');
    expect(textColor('#123456')).toBe('#ffffff');
  });

  it('draws headings, bullets, bold and https links', () => {
    const text = '# Threshold\n**Depth:** 0.3 m\n- one\n- two\n[source](https://example.org/a)';
    render(<Note data={{ code: text, appearance: { backgroundColor: 'green' } }} />);
    expect(screen.getByText('Threshold')).toBeInTheDocument();
    expect(screen.getByText('Depth:').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['one', 'two']);
    const link = screen.getByRole('link', { name: 'source' });
    expect(link).toHaveAttribute('href', 'https://example.org/a');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('never renders HTML, and shows a link that is not https as text', () => {
    const { container } = render(
      <Note data={{ content: '<img src=x onerror=alert(1)> [bad](javascript:alert(1))' }} />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
    expect(container.textContent).toContain('bad (javascript:alert(1))');
  });

  it('says so when empty', () => {
    render(<Note data={{ code: '  ' }} />);
    expect(screen.getByText('An empty note.')).toBeInTheDocument();
  });
});
