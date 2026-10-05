/**
 * A menu on the top bar (File, View and Share on the canvas, Share on the
 * dashboard). The old bar's menus closed only on a click elsewhere, had no
 * Escape, announced nothing about being open, and made each row a div wrapping
 * an inert button.
 */
import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { faPlus } from '@fortawesome/free-solid-svg-icons';

import { HeaderMenu, HeaderMenuDivider, HeaderMenuItem } from '../../components/menus/top/HeaderMenu';

function Harness({ onPick = () => {} }: { onPick?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button">elsewhere</button>
      <HeaderMenu label="File" open={open} onToggle={() => setOpen((o) => !o)} onClose={() => setOpen(false)}>
        <HeaderMenuItem icon={faPlus} onClick={onPick}>
          New dataflow
        </HeaderMenuItem>
        <HeaderMenuDivider />
        <HeaderMenuItem icon={faPlus} disabled>
          Save dataflow
        </HeaderMenuItem>
      </HeaderMenu>
    </>
  );
}

const trigger = () => screen.getByRole('button', { name: 'File menu' });

test('the trigger is named after its menu, shows its name, and says whether it is open', () => {
  render(<Harness />);
  expect(trigger().textContent).toBe('File');
  expect(trigger().className).toContain('menuCaret');
  expect(trigger().getAttribute('aria-expanded')).toBe('false');

  fireEvent.click(trigger());
  expect(trigger().getAttribute('aria-expanded')).toBe('true');
  const panel = document.getElementById(trigger().getAttribute('aria-controls')!);
  expect(panel).not.toBeNull();
});

test('the panel is the trigger\'s next sibling, and opens on its first row', () => {
  // test_no_project_menu.py finds the File menu's first row this way.
  render(<Harness />);
  fireEvent.click(trigger());
  const first = trigger().nextElementSibling!.firstElementChild!;
  expect(first.textContent).toBe('New dataflow');
});

test('rows are buttons, chosen by name, and a disabled one does nothing', () => {
  const onPick = jest.fn();
  render(<Harness onPick={onPick} />);
  fireEvent.click(trigger());

  fireEvent.click(screen.getByRole('button', { name: 'New dataflow' }));
  expect(onPick).toHaveBeenCalledTimes(1);
  expect((screen.getByRole('button', { name: 'Save dataflow' }) as HTMLButtonElement).disabled).toBe(true);
});

test('Escape closes it', () => {
  render(<Harness />);
  fireEvent.click(trigger());
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(trigger().getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByRole('button', { name: 'New dataflow' })).toBeNull();
});

test('a click anywhere else closes it, a click inside does not', () => {
  render(<Harness />);
  fireEvent.click(trigger());

  fireEvent.click(screen.getByRole('separator'));
  expect(trigger().getAttribute('aria-expanded')).toBe('true');

  fireEvent.click(screen.getByRole('button', { name: 'elsewhere' }));
  expect(trigger().getAttribute('aria-expanded')).toBe('false');
});
