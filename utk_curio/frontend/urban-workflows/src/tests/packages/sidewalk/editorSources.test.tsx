import React from 'react';
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { Harness, ready } from '../../_support/sidewalkEditorHarness';

test('the on-image source icon opens details without changing the active tool or draft', async () => {
  const persisted = jest.fn();
  const view = render(<Harness onPersist={persisted} />);
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Draw edges' }));
  expect(screen.getByRole('button', { name: 'Cancel edge drawing' })).toHaveAttribute('aria-pressed', 'true');
  const button = screen.getByRole('button', { name: 'Data sources' });
  expect(button.style.borderRadius).toBe('');
  expect(button).toHaveStyle({ background: 'transparent', color: '#000000', width: '40px', height: '40px' });
  expect(button.style.filter).toBe('');
  expect(button.querySelector('svg[data-icon="circle-info"]')).toBeInTheDocument();
  expect(button.parentElement).not.toHaveAttribute('role', 'button');
  fireEvent.click(button);
  const dialog = screen.getByRole('dialog', { name: 'Data sources' });
  expect(dialog).toHaveStyle({ paddingTop: '6px', paddingRight: '10px', paddingBottom: '10px', paddingLeft: '10px' });
  expect(dialog).not.toHaveTextContent('Read-only. Configure sources through workflow inputs.');
  const close = within(dialog).getByRole('button', { name: 'Close data sources' });
  expect(close.querySelector('svg[data-icon="xmark"]')).toBeInTheDocument();
  expect(close).toHaveStyle({ fontSize: '12px' });
  expect(dialog).toHaveTextContent('image-A.png');
  expect(dialog).toHaveTextContent('network-A.geojson');
  const imageSource = within(dialog).getByText('image-A.png');
  const copyImage = within(dialog).getByRole('button', { name: 'Copy image source' });
  expect(imageSource).toContainElement(copyImage);
  expect(imageSource.style.color).toBe('var(--curio-text-muted)');
  expect(copyImage).toHaveStyle({ position: 'absolute', top: '3px', right: '3px' });
  expect(copyImage.style.borderRadius).toBe('var(--curio-radius-sm)');
  expect(copyImage.style.color).toBe('var(--curio-text-secondary)');
  expect(copyImage.querySelector('svg[data-icon="copy"]')).toBeInTheDocument();
  expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.pointerDown(dialog);
  fireEvent.keyDown(dialog, { key: 'd' });
  expect(screen.getByRole('button', { name: 'Cancel edge drawing' })).toHaveAttribute('aria-pressed', 'true');
  expect(persisted).not.toHaveBeenCalledWith(expect.objectContaining({ imageUrlTemplate: 'image-A.png' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close data sources' }));
  expect(screen.queryByRole('dialog', { name: 'Data sources' })).not.toBeInTheDocument();
  expect(button).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Cancel edge drawing' })).toHaveAttribute('aria-pressed', 'true');
  view.unmount();
});

test('source details copy resolved paths and close on Escape or outside pointer without editing geometry', async () => {
  const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  try {
    const view = render(<Harness />);
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Data sources' }));
    fireEvent.click(screen.getByRole('button', { name: 'Copy image source' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('image-A.png'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Data sources' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Data sources' }));
    fireEvent.pointerDown(document.body);
    fireEvent.click(document.body);
    expect(screen.queryByRole('dialog', { name: 'Data sources' })).not.toBeInTheDocument();
    expect(screen.getByText('1 lines')).toBeInTheDocument();
    view.unmount();
  } finally {
    if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard);
    else Reflect.deleteProperty(navigator, 'clipboard');
  }
});
