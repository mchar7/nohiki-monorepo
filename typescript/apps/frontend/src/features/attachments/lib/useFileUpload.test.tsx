import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useFileUpload } from './useFileUpload.ts';

const { completeUpload, initiateUpload, toastError, toastSuccess } = vi.hoisted(() => ({
  completeUpload: vi.fn(),
  initiateUpload: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock('../api/index.ts', () => ({
  useCompleteUpload: () => ({ mutateAsync: completeUpload }),
  useInitiateUpload: () => ({ mutateAsync: initiateUpload }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values?.reason ? `${key}:${String(values.reason)}` : key,
  }),
}));

vi.mock('sonner', () => ({
  toast: { error: toastError, success: toastSuccess },
}));

const file = new File(['document'], 'resume.pdf', { type: 'application/pdf' });

describe('useFileUpload direct upload headers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    completeUpload.mockResolvedValue(undefined);
  });

  test('sends Azure BlockBlob header together with the declared Content-Type', async () => {
    initiateUpload.mockResolvedValue({
      upload_id: 'upload-azure',
      upload_url: 'https://storage.example.test/container/blob?sas=token',
      upload_headers: { 'x-ms-blob-type': 'BlockBlob' },
    });
    const { result } = renderHook(() => useFileUpload());

    await act(() => result.current.handleUpload(file));

    expect(fetch).toHaveBeenCalledWith(
      'https://storage.example.test/container/blob?sas=token',
      expect.objectContaining({
        method: 'PUT',
        body: file,
        headers: {
          'Content-Type': 'application/pdf',
          'x-ms-blob-type': 'BlockBlob',
        },
      }),
    );
  });

  test('sends no provider headers when S3 returns an empty header map', async () => {
    initiateUpload.mockResolvedValue({
      upload_id: 'upload-s3',
      upload_url: 'https://account.blob.core.windows.net/container/blob?sas=looks-azure',
      upload_headers: {},
    });
    const { result } = renderHook(() => useFileUpload());

    await act(() => result.current.handleUpload(file));

    expect(fetch).toHaveBeenCalledWith(
      'https://account.blob.core.windows.net/container/blob?sas=looks-azure',
      expect.objectContaining({ headers: { 'Content-Type': 'application/pdf' } }),
    );
  });

  test('keeps upload failure behavior when the direct PUT fails', async () => {
    initiateUpload.mockResolvedValue({
      upload_id: 'upload-failure',
      upload_url: 'https://storage.example.test/container/blob?sas=token',
      upload_headers: { 'x-ms-blob-type': 'BlockBlob' },
    });
    vi.mocked(fetch).mockResolvedValue({ ok: false } as Response);
    const onComplete = vi.fn();
    const { result } = renderHook(() => useFileUpload(onComplete));

    await act(() => result.current.handleUpload(file));

    expect(completeUpload).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith('attachments:validation.uploadFailed:Upload failed');
    expect(result.current).toMatchObject({
      isUploading: false,
      uploadProgress: 0,
      lastUploadId: null,
    });
  });
});
