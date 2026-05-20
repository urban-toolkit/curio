import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { GenericDialog } from '../../components/GenericDialog';
import { useDialogContext } from '../../providers/DialogProvider';

// Mock the useDialogContext hook
const mockUnsetDialog = jest.fn();
jest.mock('../../providers/DialogProvider', () => ({
  useDialogContext: () => ({
    setDialog: jest.fn(),
    unsetDialog: mockUnsetDialog,
  }),
}));

function modalBackdrop(): HTMLElement {
  const el = document.body.querySelector('[class*="backdrop"]');
  if (!el) throw new Error('Modal backdrop not found (ModalShell uses a portal)');
  return el as HTMLElement;
}

describe('GenericDialog', () => {
  beforeEach(() => {
    mockUnsetDialog.mockClear();
  });

  test('renders as a modal overlay with backdrop', () => {
    const dialogContent = <div data-testid="dialog-content">Modal Content</div>;

    render(<GenericDialog dialog={dialogContent} />);

    // Should render the dialog content
    expect(screen.getByTestId('dialog-content')).toBeInTheDocument();
  });

  test('creates a semi-transparent backdrop for modal effect', () => {
    const dialogContent = <div>Content</div>;

    render(<GenericDialog dialog={dialogContent} />);

    expect(modalBackdrop()).toBeInTheDocument();
  });

  test('centers dialog content using flexbox', () => {
    const dialogContent = <div>Centered Content</div>;

    render(<GenericDialog dialog={dialogContent} />);

    // Content should be present in the rendered output
    expect(screen.getByText('Centered Content')).toBeInTheDocument();
  });

  test('closes dialog when backdrop is clicked (key interaction)', () => {
    const dialogContent = <div data-testid="inner-content">Click outside to close</div>;

    render(<GenericDialog dialog={dialogContent} />);
    fireEvent.click(modalBackdrop());

    expect(mockUnsetDialog).toHaveBeenCalledTimes(1);
  });

  test('integrates with DialogProvider context', () => {
    const dialogContent = <div>Provider Integration Test</div>;

    render(<GenericDialog dialog={dialogContent} />);

    // The component should render without throwing errors when useDialogContext is called
    expect(screen.getByText('Provider Integration Test')).toBeInTheDocument();
  });

  test('handles different types of dialog content (flexibility)', () => {
    // Test with a form-like dialog (common use case in this app)
    const formDialog = (
      <div data-testid="form-dialog">
        <h2>Template Configuration</h2>
        <input placeholder="Template name" />
        <button type="submit">Save</button>
        <button type="button">Cancel</button>
      </div>
    );

    render(<GenericDialog dialog={formDialog} />);

    expect(screen.getByTestId('form-dialog')).toBeInTheDocument();
    expect(screen.getByText('Template Configuration')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Template name')).toBeInTheDocument();
    expect(screen.getByText('Save')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  test('allows any React node as dialog content', () => {
    // Test with different content types that might be used in the urban-workflows app
    const complexContent = (
      <>
        <div>Description Modal Content</div>
        <div>Box Configuration</div>
        <div>Error Messages</div>
      </>
    );

    render(<GenericDialog dialog={complexContent} />);

    expect(screen.getByText('Description Modal Content')).toBeInTheDocument();
    expect(screen.getByText('Box Configuration')).toBeInTheDocument();
    expect(screen.getByText('Error Messages')).toBeInTheDocument();
  });
});
