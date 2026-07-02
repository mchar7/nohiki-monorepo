import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import { UploadDialog } from './UploadDialog.tsx';

let mockIsMobile = false;
let mockIsUploading = false;
let mockUploadProgress = 0;
const mockHandleUpload: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue(undefined);

const MOCK_UPLOAD_PROGRESS_PERCENT = 50;

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockIsMobile,
  };
});

vi.mock('../lib/useFileUpload.ts', () => ({
  useFileUpload: () => ({
    isUploading: mockIsUploading,
    uploadProgress: mockUploadProgress,
    handleUpload: mockHandleUpload,
  }),
}));

describe('UploadDialog rendering', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
    mockIsUploading = false;
    mockUploadProgress = 0;
  });

  test('renders Dialog on desktop and displays drop zone', async () => {
    mockIsMobile = false;
    render(<UploadDialog />);
    const trigger = screen.getByRole('button', { name: 'Upload File' });
    await userEvent.click(trigger);
    expect(screen.getByText('Upload Document')).toBeInTheDocument();
    expect(screen.getByText('Drag and drop a file here, or click to browse')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="dialog-content"]')).toBeInTheDocument();
  });

  test('renders BottomSheet on mobile', async () => {
    mockIsMobile = true;
    render(<UploadDialog />);
    const trigger = screen.getByRole('button', { name: 'Upload File' });
    await userEvent.click(trigger);
    expect(screen.getByText('Upload Document')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="sheet-content"]')).toBeInTheDocument();
  });
});

describe('UploadDialog file upload', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
    mockIsUploading = false;
    mockUploadProgress = 0;
  });

  test('triggers upload when file is selected', async () => {
    render(<UploadDialog />);
    await userEvent.click(screen.getByRole('button', { name: 'Upload File' }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['dummy content'], 'resume.pdf', { type: 'application/pdf' });
    await userEvent.upload(input, file);
    expect(mockHandleUpload).toHaveBeenCalledWith(file);
  });

  test('shows upload progress when uploading', async () => {
    mockIsUploading = true;
    mockUploadProgress = MOCK_UPLOAD_PROGRESS_PERCENT;
    render(<UploadDialog />);
    await userEvent.click(screen.getByRole('button', { name: 'Upload File' }));
    expect(screen.getByText('Uploading...')).toBeInTheDocument();
    const progress = screen.getByRole('progressbar');
    expect(progress).toBeInTheDocument();
  });
});

describe('UploadDialog drag and drop', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
    mockIsUploading = false;
    mockUploadProgress = 0;
  });

  test('changes text and styling on drag over', async () => {
    render(<UploadDialog />);
    await userEvent.click(screen.getByRole('button', { name: 'Upload File' }));
    const dropzone = screen
      .getByText('Drag and drop a file here, or click to browse')
      .closest('button');
    if (!dropzone) {
      throw new Error('Dropzone not found');
    }
    fireEvent.dragEnter(dropzone);
    expect(screen.getByText('Drop the file here...')).toBeInTheDocument();
    expect(dropzone.className).toContain('bg-primary/10');
    fireEvent.dragLeave(dropzone);
    expect(screen.getByText('Drag and drop a file here, or click to browse')).toBeInTheDocument();
  });

  test('disables input when uploading', async () => {
    mockIsUploading = true;
    render(<UploadDialog />);
    await userEvent.click(screen.getByRole('button', { name: 'Upload File' }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeDisabled();
    const dropzone = document.querySelector('button[disabled]') as HTMLButtonElement;
    expect(dropzone).toBeDisabled();
  });
});
