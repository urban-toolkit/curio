import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { Harness } from '../../_support/sidewalkEditorHarness';

test('editing modes and icon commands have the approved order, labels, and active instruction', async () => {
  render(<Harness />);
  const toolbar = screen.getByRole('toolbar', { name: 'Sidewalk network editing tools' });
  const buttons = within(toolbar).getAllByRole('button');
  expect(buttons.map(button => button.getAttribute('aria-label'))).toEqual([
    'Inspect Street View', 'Draw edges', 'Move nodes', 'Delete', 'Undo', 'Redo',
  ]);
  expect(buttons.slice(0, 3).map(button => button.textContent?.trim())).toEqual([
    'Inspect Street View', 'Draw edges', 'Move nodes',
  ]);
  expect(buttons.slice(3).every(button => button.textContent?.trim() === '')).toBe(true);
  expect(buttons.slice(0, 3).every(button => button.classList.contains('sidewalk-mode-command'))).toBe(true);
  expect(toolbar.querySelector('.sidewalk-history-divider')).toBeNull();
  expect(buttons[3]).toHaveStyle({ color: 'var(--curio-danger-text)' });
  expect(buttons.every(button => button.title.length > 0)).toBe(true);
  expect(screen.getByText('Choose a tool to edit the network, or select a node.')).toBeInTheDocument();
  fireEvent.load(await screen.findByRole('img'));
  fireEvent.click(screen.getByRole('button', { name: 'Move nodes' }));
  expect(screen.getByText('Drag a node to reposition it.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Move nodes' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Redo' })).toBeDisabled();
});
