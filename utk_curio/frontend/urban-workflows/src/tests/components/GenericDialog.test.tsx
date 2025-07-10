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

describe('GenericDialog', () => {
  beforeEach(() => {
    mockUnsetDialog.mockClear();
  });

  test('renders as a modal overlay with backdrop', () => {
    const dialogContent = <div data-testid="dialog-content">Modal Content</div>;
    
    const { container } = render(<GenericDialog dialog={dialogContent} />);
    const backdrop = container.firstChild as HTMLElement;
    
    // Should render the dialog content
    expect(screen.getByTestId('dialog-content')).toBeInTheDocument();
    
    // Should create a full-screen overlay
    expect(backdrop).toHaveStyle({
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100%',
      height: '100%',
    });
  });

  test('creates a semi-transparent backdrop for modal effect', () => {
    const dialogContent = <div>Content</div>;
    
    const { container } = render(<GenericDialog dialog={dialogContent} />);
    const backdrop = container.firstChild as HTMLElement;
    
    expect(backdrop).toHaveStyle({
      backgroundColor: 'rgba(0, 0, 0, 0.5)',
    });
  });

  test('centers dialog content using flexbox', () => {
    const dialogContent = <div>Centered Content</div>;
    
    const { container } = render(<GenericDialog dialog={dialogContent} />);
    const backdrop = container.firstChild as HTMLElement;
    
    expect(backdrop).toHaveStyle({
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
    });
  });

  test('closes dialog when backdrop is clicked (key interaction)', () => {
    const dialogContent = <div data-testid="inner-content">Click outside to close</div>;
    
    const { container } = render(<GenericDialog dialog={dialogContent} />);
    const backdrop = container.firstChild as HTMLElement;
    
    // Click on the backdrop (not the inner content)
    fireEvent.click(backdrop);
    
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