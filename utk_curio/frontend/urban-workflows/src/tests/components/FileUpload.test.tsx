import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import FileUpload from '../../components/menus/upload/FileUpload';

// Mock process.env for backend URL
process.env.BACKEND_URL = 'http://localhost:5002';

// Mock fetch for file upload testing
global.fetch = jest.fn();

// Mock File API
const createMockFile = (name: string, size: number, type: string) => {
  const file = new File([''], name, { type });
  Object.defineProperty(file, 'size', {
    value: size,
    writable: false,
  });
  return file;
};

describe('FileUpload Interface Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it('renders upload button in idle state with correct icon', () => {
    render(<FileUpload />);
    
    const uploadButton = screen.getByRole('button');
    expect(uploadButton).toBeInTheDocument();
    expect(uploadButton).not.toBeDisabled();
    
    // Should show upload icon in idle state
    const uploadIcon = uploadButton.querySelector('svg');
    expect(uploadIcon).toBeInTheDocument();
  });

  it('handles file selection interaction through hidden input', () => {
    render(<FileUpload />);
    
    const uploadButton = screen.getByRole('button');
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    
    expect(fileInput).toBeInTheDocument();
    expect(fileInput?.style.display).toBe('none');
    
    // Mock the click method
    const mockClick = jest.spyOn(fileInput, 'click').mockImplementation(() => {});
    
    // Clicking upload button should trigger file input
    fireEvent.click(uploadButton);
    expect(mockClick).toHaveBeenCalled();
    
    mockClick.mockRestore();
  });

  it('initiates upload process when file is selected', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve('Upload successful'),
    } as Response);

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('test.csv', 1024, 'text/csv');
    
    // Simulate file selection
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Should eventually show success state (upload completes quickly with mock)
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      expect(uploadButton).not.toBeDisabled();
      const successIcon = uploadButton.querySelector('svg[data-icon="check"]');
      expect(successIcon).toBeInTheDocument();
    });
    
    // Verify fetch was called with correct parameters
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:5002/upload',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      })
    );
  });

  it('displays success state after successful upload', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve('Upload successful'),
    } as Response);

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('success.json', 2048, 'application/json');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Wait for upload to complete and success state
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      expect(uploadButton).not.toBeDisabled();
      // Success icon should be visible (check mark)
      const successIcon = uploadButton.querySelector('svg[data-icon="check"]');
      expect(successIcon).toBeInTheDocument();
    });
  });

  it('displays error state when upload fails', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    // Mock console.error to avoid test output pollution
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('error.txt', 512, 'text/plain');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Wait for upload to fail and error state
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      expect(uploadButton).not.toBeDisabled();
      // Error icon should be visible (X mark)
      const errorIcon = uploadButton.querySelector('svg[data-icon="xmark"]');
      expect(errorIcon).toBeInTheDocument();
    });

    consoleSpy.mockRestore();
  });

  it('handles server error response (non-200 status)', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
    } as Response);

    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('server-error.pdf', 1024, 'application/pdf');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Should show error state for server errors
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      const errorIcon = uploadButton.querySelector('svg[data-icon="xmark"]');
      expect(errorIcon).toBeInTheDocument();
    });

    consoleSpy.mockRestore();
  });

  it('resets to idle state after success/error timeout', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve('Upload successful'),
    } as Response);

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('timeout-test.txt', 256, 'text/plain');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Wait for success state
    await waitFor(() => {
      const successIcon = screen.getByRole('button').querySelector('svg[data-icon="check"]');
      expect(successIcon).toBeInTheDocument();
    });
    
    // Fast-forward time to trigger reset
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    
    // Should return to idle state (upload icon)
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      const uploadIcon = uploadButton.querySelector('svg[data-icon="file-arrow-up"]');
      expect(uploadIcon).toBeInTheDocument();
    });
  });

  it('prevents multiple uploads when upload is in progress', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    // Make fetch hang to simulate ongoing upload
    mockFetch.mockImplementationOnce(() => new Promise(() => {}));

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('ongoing.zip', 5120, 'application/zip');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Button should be disabled during upload
    await waitFor(() => {
      const uploadButton = screen.getByRole('button');
      expect(uploadButton).toBeDisabled();
    });
    
    // File input should also be disabled
    expect(fileInput).toBeDisabled();
    
    // Clicking button should have no effect
    const uploadButton = screen.getByRole('button');
    const clickSpy = jest.spyOn(fileInput, 'click');
    
    fireEvent.click(uploadButton);
    expect(clickSpy).not.toHaveBeenCalled();
    
    clickSpy.mockRestore();
  });

  it('handles empty file selection gracefully', () => {
    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    
    // Simulate no file selected
    Object.defineProperty(fileInput, 'files', {
      value: [],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // Should remain in idle state
    const uploadButton = screen.getByRole('button');
    expect(uploadButton).not.toBeDisabled();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('constructs FormData correctly with file and filename', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve('Upload successful'),
    } as Response);

    render(<FileUpload />);
    
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const testFile = createMockFile('important-data.xlsx', 4096, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    
    Object.defineProperty(fileInput, 'files', {
      value: [testFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
    });
    
    // Verify FormData was constructed with correct file and filename
    const fetchCall = mockFetch.mock.calls[0];
    const formData = fetchCall[1]?.body as FormData;
    
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get('file')).toBe(testFile);
    expect(formData.get('fileName')).toBe('important-data.xlsx');
  });

  it('demonstrates complete user workflow: select → upload → success → reset', async () => {
    const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve('Workflow complete'),
    } as Response);

    render(<FileUpload />);
    
    // 1. Initial state: idle with upload icon
    const uploadButton = screen.getByRole('button');
    expect(uploadButton).not.toBeDisabled();
    
    // 2. User clicks to select file
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const mockClick = jest.spyOn(fileInput, 'click').mockImplementation(() => {});
    
    fireEvent.click(uploadButton);
    expect(mockClick).toHaveBeenCalled();
    
    // 3. User selects a file
    const workflowFile = createMockFile('user-workflow.json', 1024, 'application/json');
    Object.defineProperty(fileInput, 'files', {
      value: [workflowFile],
      writable: false,
    });
    
    fireEvent.change(fileInput);
    
    // 4. Upload completes: success state (mock resolves immediately)
    await waitFor(() => {
      expect(uploadButton).not.toBeDisabled();
      const successIcon = uploadButton.querySelector('svg[data-icon="check"]');
      expect(successIcon).toBeInTheDocument();
    });
    
    // 5. Upload completes: success state
    await waitFor(() => {
      expect(uploadButton).not.toBeDisabled();
      const successIcon = uploadButton.querySelector('svg[data-icon="check"]');
      expect(successIcon).toBeInTheDocument();
    });
    
    // 6. Auto-reset after timeout
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    
    await waitFor(() => {
      const uploadIcon = uploadButton.querySelector('svg[data-icon="file-arrow-up"]');
      expect(uploadIcon).toBeInTheDocument();
    });
    
    // Complete workflow tested!
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:5002/upload',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      })
    );
    
    mockClick.mockRestore();
  });
}); 