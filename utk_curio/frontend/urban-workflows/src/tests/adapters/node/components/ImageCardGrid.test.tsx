/**
 * The card grid that replaced the bare thumbnail grid (#276).
 *
 * The old grid drew 50px images and nothing else, so retiring the CV Gallery
 * would have lost the per-image values it showed beside each picture. A card
 * carries the row that produced the image, and can carry more than one image
 * column, which is how source and segmentation sit side by side.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import ImageCardGrid from '../../../../adapters/node/components/ImageCardGrid';

jest.mock('../../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../../../utils/authApi', () => ({ getToken: () => 'tok-123' }));

const rows = [
  { image_url: 'https://example.test/a?size=640', image_id: 'CAoSL1', dominant_class: 'vegetation' },
  { image_url: 'https://example.test/b?size=640', image_id: 'CAoSL2', dominant_class: 'road' },
];

const defaultProps = {
  nodeId: 'sv-1',
  rows,
  imageColumns: ['image_url'],
  interacted: ['0', '0'],
  onClickRow: jest.fn(),
};

describe('ImageCardGrid', () => {
  beforeEach(() => jest.clearAllMocks());

  it('draws one image per row', () => {
    render(<ImageCardGrid {...defaultProps} />);
    const imgs = screen.getAllByRole('img');
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toHaveAttribute('src', 'https://example.test/a?size=640');
  });

  it('captions each card with the rest of its row', () => {
    render(<ImageCardGrid {...defaultProps} />);
    expect(screen.getByText('image_id: CAoSL1')).toBeInTheDocument();
    expect(screen.getByText('dominant_class: vegetation')).toBeInTheDocument();
  });

  it('draws every requested image column side by side', () => {
    const twoColumns = rows.map((r) => ({ ...r, overlay_url: 'https://example.test/o.png' }));
    render(
      <ImageCardGrid
        {...defaultProps}
        rows={twoColumns}
        imageColumns={['image_url', 'overlay_url']}
      />,
    );
    expect(screen.getAllByRole('img')).toHaveLength(4);
  });

  it('reports the row index, not a flattened image index', () => {
    const onClickRow = jest.fn();
    render(<ImageCardGrid {...defaultProps} onClickRow={onClickRow} />);
    fireEvent.click(document.getElementById('imageBox_content_sv-1_1')!);
    expect(onClickRow).toHaveBeenCalledWith(1);
  });

  it('outlines a card the linked pool marked as interacted', () => {
    const { container } = render(<ImageCardGrid {...defaultProps} interacted={['1', '0']} />);
    const cards = container.querySelectorAll('[id^="imageBox_content_sv-1_"]');
    expect(cards[0]).toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
    expect(cards[1]).not.toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
  });

  it('ignores an interacted array that does not line up with the rows', () => {
    const { container } = render(<ImageCardGrid {...defaultProps} interacted={['1']} />);
    const cards = container.querySelectorAll('[id^="imageBox_content_sv-1_"]');
    expect(cards[0]).not.toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
  });

  it('fetches a same-origin /api image with the bearer token and revokes its blob', async () => {
    // A bare <img src> cannot send a header, and the route behind /api resolves
    // which user is asking from that header, so this path is the whole reason
    // overlays can live in a column at all.
    const blob = new Blob(['png'], { type: 'image/png' });
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(blob) });
    (global as any).fetch = fetchMock;
    const createObjectURL = jest.fn(() => 'blob:overlay-1');
    const revokeObjectURL = jest.fn();
    (global as any).URL.createObjectURL = createObjectURL;
    (global as any).URL.revokeObjectURL = revokeObjectURL;

    const authed = [{ overlay_url: '/api/streetvision/inference/overlay/a.jpg', image_id: 'a' }];
    let view: any;
    await act(async () => {
      view = render(
        <ImageCardGrid
          {...defaultProps}
          rows={authed}
          imageColumns={['overlay_url']}
          interacted={['0']}
        />,
      );
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://backend.test/api/streetvision/inference/overlay/a.jpg',
      { headers: { Authorization: 'Bearer tok-123' } },
    );
    await waitFor(() => {
      expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:overlay-1');
    });

    view.unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:overlay-1');
  });

  it('holds the slot instead of throwing when an authed image fails', async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
    const authed = [{ overlay_url: '/api/streetvision/inference/overlay/missing.jpg' }];
    await act(async () => {
      render(
        <ImageCardGrid
          {...defaultProps}
          rows={authed}
          imageColumns={['overlay_url']}
          interacted={['0']}
        />,
      );
    });
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect(document.getElementById('imageBox_content_sv-1_0')).toBeInTheDocument();
  });
});
