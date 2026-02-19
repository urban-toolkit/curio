import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ImageGrid from '../../../../adapters/box/components/ImageGrid';

describe('ImageGrid', () => {
  const defaultProps = {
    nodeId: 'img-1',
    images: ['data:image/png;base64,AAA', 'data:image/png;base64,BBB'],
    interacted: ['0', '0'],
    onClickImage: jest.fn(),
  };

  beforeEach(() => {
    defaultProps.onClickImage.mockClear();
  });

  test('renders one img element per image', () => {
    render(<ImageGrid {...defaultProps} />);
    const images = screen.getAllByRole('img');
    expect(images).toHaveLength(2);
  });

  test('sets correct src on each image', () => {
    render(<ImageGrid {...defaultProps} />);
    const images = screen.getAllByRole('img');
    expect(images[0]).toHaveAttribute('src', 'data:image/png;base64,AAA');
    expect(images[1]).toHaveAttribute('src', 'data:image/png;base64,BBB');
  });

  test('calls onClickImage with the correct index', () => {
    render(<ImageGrid {...defaultProps} />);
    const images = screen.getAllByRole('img');

    fireEvent.click(images[1]);
    expect(defaultProps.onClickImage).toHaveBeenCalledWith(1);

    fireEvent.click(images[0]);
    expect(defaultProps.onClickImage).toHaveBeenCalledWith(0);
  });

  test('applies selected style when interacted[i] === "1"', () => {
    render(
      <ImageGrid
        {...defaultProps}
        interacted={['1', '0']}
      />,
    );
    const images = screen.getAllByRole('img');
    expect(images[0]).toHaveStyle({ border: '3px solid red' });
    expect(images[1]).not.toHaveStyle({ border: '3px solid red' });
  });

  test('does not apply selected style when interacted array length differs from images', () => {
    render(
      <ImageGrid
        {...defaultProps}
        interacted={['1']}
      />,
    );
    const images = screen.getAllByRole('img');
    expect(images[0]).not.toHaveStyle({ border: '3px solid red' });
  });

  test('renders container with correct id', () => {
    const { container } = render(<ImageGrid {...defaultProps} />);
    expect(container.querySelector('#imageBox_content_img-1')).toBeTruthy();
  });

  test('renders empty grid when images array is empty', () => {
    const { container } = render(
      <ImageGrid {...defaultProps} images={[]} interacted={[]} />,
    );
    expect(container.querySelectorAll('img')).toHaveLength(0);
  });
});
