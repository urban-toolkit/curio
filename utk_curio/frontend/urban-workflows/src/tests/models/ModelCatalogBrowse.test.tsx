import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { ModelCatalogBrowse } from '../../pages/models/ModelCatalogBrowse';
import { invalidateModelCatalogCache } from '../../services/modelCatalog';
import type { ModelRow } from '../../services/modelCatalog';
import { downloadedModel, shippedModel } from '../_support/modelRows';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));

const mockShowToast = jest.fn();
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

/** Route the mocked client by method and path, so a test can serve the
 *  listing, a model, its license and a delete without caring about order. */
function routeApi(rows: ModelRow[], extra: { license?: string } = {}) {
  apiFetch.mockImplementation((path: string, init: RequestInit = {}) => {
    if (init.method === 'DELETE') return Promise.resolve({ deleted: path.split('/').pop() });
    if (path.startsWith('/api/models/catalog')) return Promise.resolve({ items: rows });
    if (path.endsWith('/license')) return Promise.resolve({ text: extra.license ?? '' });
    const id = decodeURIComponent(path.replace('/api/models/', ''));
    const row = rows.find((r) => r.id === id);
    if (row) return Promise.resolve(row);
    return Promise.reject(Object.assign(new Error('no model'), { status: 404 }));
  });
}

/** The card for one model. Scoped because a runtime or origin label appears
 *  in the rail, the chips and the card alike. */
function card(id: string): HTMLElement {
  const el = document.querySelector(`.cardGrid [data-model-id="${id}"]`);
  if (!el) throw new Error(`no card for ${id}`);
  return el as HTMLElement;
}

let location = '';
const LocationProbe: React.FC = () => {
  location = useLocation().pathname;
  return null;
};

function renderPage(entry = '/catalog/models') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/catalog/models/:modelId?" element={<ModelCatalogBrowse />} />
        <Route path="/catalog/discovery/:sourceDir" element={<div>source page</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>
  );
}

const details = () => screen.queryByRole('dialog', { name: 'Model details' });

beforeEach(() => {
  invalidateModelCatalogCache();
  apiFetch.mockReset();
  mockShowToast.mockReset();
});

describe('ModelCatalogBrowse', () => {
  test('a card shows the name, publisher, runtime, label count, size and license', async () => {
    routeApi([shippedModel()]);
    renderPage();
    await screen.findAllByText('DDRNet23-Slim (street scenes)');
    const tile = within(card('model.curio.ddrnet23-slim'));
    expect(tile.getByText('DDRNet23-Slim (street scenes)')).toBeInTheDocument();
    expect(tile.getByText('Curio')).toBeInTheDocument();
    expect(tile.getByText('ONNX')).toBeInTheDocument();
    expect(tile.getByText('3 labels · 23.0 MB')).toBeInTheDocument();
    expect(tile.getByText('MIT; trained on Cityscapes')).toBeInTheDocument();
    expect(tile.getByText('Shipped with Curio')).toBeInTheDocument();
  });

  test('it asks the backend to search, with q', async () => {
    routeApi([shippedModel()]);
    renderPage();
    await screen.findAllByText('DDRNet23-Slim (street scenes)');
    expect(apiFetch).toHaveBeenCalledWith('/api/models/catalog');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search models' }), {
      target: { value: 'street' },
    });
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith('/api/models/catalog?q=street'));
  });

  test('the drawer opens on the first model, as on the other catalog pages', async () => {
    routeApi([shippedModel(), downloadedModel()]);
    renderPage();
    await screen.findAllByText('SegFormer B0 (ADE20K)');
    const drawer = document.querySelector('[data-curio-browse-drawer]') as HTMLElement;
    expect(drawer).not.toBeNull();
    expect(within(drawer).getByText('Model info')).toBeInTheDocument();
    expect(card('model.curio.ddrnet23-slim').className).toMatch(/cardActive/);
  });

  test('the runtime and origin chips narrow the grid', async () => {
    routeApi([shippedModel(), downloadedModel()]);
    renderPage();
    await screen.findAllByText('SegFormer B0 (ADE20K)');
    fireEvent.click(document.querySelector('[data-curio-runtime-chip="transformers"]') as HTMLElement);
    expect(document.querySelector('.cardGrid [data-model-id="model.curio.ddrnet23-slim"]')).toBeNull();
    expect(card('imported.xabc123def456')).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-curio-origin-chip="shipped"]') as HTMLElement);
    expect(screen.getByText('No models match the current filters.')).toBeInTheDocument();
  });

  test('an empty catalog says so', async () => {
    routeApi([]);
    renderPage();
    expect(await screen.findByText('Your Model Catalog is empty.')).toBeInTheDocument();
  });

  test('a failed load surfaces the error and keeps a retry', async () => {
    apiFetch.mockRejectedValue(new Error('backend is down'));
    renderPage();
    expect(await screen.findByText('backend is down')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

describe('ModelCatalogBrowse: details', () => {
  test('View details shows the model, its labels as chips, and its license text', async () => {
    routeApi([shippedModel()], { license: 'MIT License\n\nCopyright (c) DDRNet' });
    renderPage();
    await screen.findAllByText('DDRNet23-Slim (street scenes)');
    fireEvent.click(within(card('model.curio.ddrnet23-slim')).getByRole('button', { name: 'View details' }));

    const modal = within(details() as HTMLElement);
    expect(modal.getByRole('heading', { name: 'DDRNet23-Slim (street scenes)' })).toBeInTheDocument();
    expect(modal.getByText('Labels every pixel of a street photo.')).toBeInTheDocument();
    expect(modal.getByText('Semantic segmentation')).toBeInTheDocument();
    expect(modal.getByText('1024 × 512, uint8')).toBeInTheDocument();
    expect(modal.getByText('23.0 MB')).toBeInTheDocument();
    const labels = document.querySelector('[data-curio-model-labels]') as HTMLElement;
    expect(Array.from(labels.children).map((el) => el.textContent)).toEqual([
      'road',
      'sidewalk',
      'building',
    ]);
    expect(modal.getByRole('link', { name: 'github.com ↗' })).toHaveAttribute(
      'href',
      'https://github.com/ydhongHIT/DDRNet'
    );

    fireEvent.click(modal.getByRole('button', { name: 'View license' }));
    await waitFor(() =>
      expect(document.querySelector('[data-curio-model-license]')?.textContent).toBe(
        'MIT License\n\nCopyright (c) DDRNet'
      )
    );
    expect(apiFetch).toHaveBeenCalledWith('/api/models/model.curio.ddrnet23-slim/license');
  });

  test('a downloaded model says where it came from, and links there', async () => {
    routeApi([downloadedModel()]);
    renderPage();
    await screen.findAllByText('SegFormer B0 (ADE20K)');
    fireEvent.click(within(card('imported.xabc123def456')).getByRole('button', { name: 'View details' }));

    const modal = within(details() as HTMLElement);
    expect(modal.getByText('Downloaded from')).toBeInTheDocument();
    expect(modal.getByText('nvidia/segformer-b0-finetuned-ade-512-512')).toBeInTheDocument();
    // No license text to show, so nothing offers to show it.
    expect(modal.queryByRole('button', { name: 'View license' })).toBeNull();
    fireEvent.click(modal.getByRole('link', { name: 'Hugging Face' }));
    expect(await screen.findByText('source page')).toBeInTheDocument();
    expect(location).toBe('/catalog/discovery/source.curio.huggingface');
  });

  test('a link to a model opens the page with its details, and closing leaves the plain page', async () => {
    routeApi([shippedModel()]);
    renderPage('/catalog/models/model.curio.ddrnet23-slim');
    expect(await screen.findByRole('heading', { name: 'Model Catalog' })).toBeInTheDocument();
    await waitFor(() => expect(details()).not.toBeNull());
    fireEvent.click(within(details() as HTMLElement).getByRole('button', { name: 'Close' }));
    expect(details()).toBeNull();
    expect(location).toBe('/catalog/models');
  });

  test('a link to a model that is not there says so', async () => {
    routeApi([shippedModel()]);
    renderPage('/catalog/models/model.gone');
    expect(await screen.findByText('This model is not in your Model Catalog.')).toBeInTheDocument();
  });
});

describe('ModelCatalogBrowse: delete', () => {
  function openMenu(id: string) {
    fireEvent.contextMenu(card(id), { clientX: 10, clientY: 20 });
    return screen.getByRole('menu', { name: 'Model actions' });
  }

  test('a shipped model offers only its details on right-click, and no Delete anywhere', async () => {
    routeApi([shippedModel()]);
    renderPage();
    await screen.findAllByText('DDRNet23-Slim (street scenes)');
    const menu = openMenu('model.curio.ddrnet23-slim');
    expect(within(menu).getAllByRole('menuitem').map((el) => el.textContent)).toEqual(['View details']);
    const drawer = document.querySelector('[data-curio-drawer-ctas]') as HTMLElement;
    expect(within(drawer).queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  test('a downloaded model offers Delete, which asks first and then deletes', async () => {
    routeApi([downloadedModel()]);
    renderPage();
    await screen.findAllByText('SegFormer B0 (ADE20K)');
    const menu = openMenu('imported.xabc123def456');
    expect(within(menu).getAllByRole('menuitem').map((el) => el.textContent)).toEqual([
      'Delete',
      'View details',
    ]);
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Delete' }));

    const confirm = await screen.findByRole('dialog', {
      name: 'Permanently delete "SegFormer B0 (ADE20K)"?',
    });
    // Nothing is deleted until the question is answered.
    expect(apiFetch).not.toHaveBeenCalledWith(
      '/api/models/imported.xabc123def456',
      expect.objectContaining({ method: 'DELETE' })
    );
    await act(async () => {
      fireEvent.click(within(confirm).getByRole('button', { name: 'Delete' }));
    });
    expect(apiFetch).toHaveBeenCalledWith('/api/models/imported.xabc123def456', { method: 'DELETE' });
    expect(mockShowToast).toHaveBeenCalledWith(
      'Deleted SegFormer B0 (ADE20K) from your Model Catalog.',
      'success'
    );
  });

  test("the drawer offers the same Delete for a downloaded model", async () => {
    routeApi([downloadedModel()]);
    renderPage();
    await screen.findAllByText('SegFormer B0 (ADE20K)');
    const drawer = document.querySelector('[data-curio-drawer-ctas]') as HTMLElement;
    fireEvent.click(within(drawer).getByRole('button', { name: 'Delete' }));
    expect(
      await screen.findByRole('dialog', { name: 'Permanently delete "SegFormer B0 (ADE20K)"?' })
    ).toBeInTheDocument();
  });
});
