import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Harness, savedConfig, ready, canvas, draw, network } from '../../_support/sidewalkEditorHarness';

test('Save/edit/undo/redo preserves commit metadata and monotonic per-tile revisions, including reopening', async () => {
  const persist = jest.fn(); const emit = jest.fn(); const interaction = jest.fn();
  const view = render(<Harness initialConfig={savedConfig({ marker: 'keep-me' })} onPersist={persist} emit={emit} interaction={interaction} />);
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  const first = persist.mock.calls.at(-1)![0].byTile.A;
  const firstEnvelope = interaction.mock.calls.at(-1)![0]['sidewalk.network-edit'];
  expect(first.revision).toBe(1);
  await draw(canvas(view.container));
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  const undone = persist.mock.calls.at(-1)![0].byTile.A;
  expect(undone).toMatchObject({ revision: 1, marker: 'keep-me', originalNetwork: first.originalNetwork,
    committedNetwork: first.committedNetwork, provenance: first.provenance, committedEdit: firstEnvelope });
  expect(undone.network).toEqual(network());
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  expect(interaction.mock.calls.at(-1)![0]['sidewalk.network-edit']).toMatchObject({ editRevision: 2, before: network(), after: network(), operationTypes: [] });
  fireEvent.click(screen.getByRole('button', { name: 'Redo' }));
  expect(persist.mock.calls.at(-1)![0].byTile.A.revision).toBe(2);
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  const config = persist.mock.calls.at(-1)![0]; const final = config.byTile.A;
  const envelope = interaction.mock.calls.at(-1)![0]['sidewalk.network-edit'];
  expect(envelope).toMatchObject({ editRevision: 3, before: network(), after: final.committedNetwork, operationTypes: ['draw_edge'] });
  expect(envelope.provenance).toMatchObject({ editRevision: 3, before: network(), after: final.committedNetwork });
  expect(emit.mock.calls.at(-1)![0].data.metadata.provenance).toEqual(envelope.provenance);
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  const draftConfig = persist.mock.calls.at(-1)![0];
  view.unmount(); interaction.mockClear();
  render(<Harness initialConfig={draftConfig} onPersist={persist} interaction={interaction} />);
  await ready();
  await waitFor(() => expect(interaction).toHaveBeenCalledWith({ 'sidewalk.network-edit': envelope }, 'test'));
  expect(draftConfig.byTile.A.committedEdit).toEqual(envelope);
  fireEvent.click(screen.getByRole('button', { name: 'Redo' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
  expect(interaction.mock.calls.at(-1)![0]['sidewalk.network-edit'].editRevision).toBe(4);
});
