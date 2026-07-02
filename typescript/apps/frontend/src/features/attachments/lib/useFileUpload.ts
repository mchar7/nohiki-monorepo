import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { extractErrorReason } from '@/shared/lib/index.ts';
import { useCompleteUpload, useInitiateUpload } from '../api/index.ts';

const MAX_FILE_SIZE_MB: number = 10;
const BYTES_PER_KB: number = 1024;
const BYTES_PER_MB: number = BYTES_PER_KB * BYTES_PER_KB;
const MAX_FILE_SIZE_BYTES: number = MAX_FILE_SIZE_MB * BYTES_PER_MB;

const UPLOAD_PROGRESS_INITIATED: number = 10;
const UPLOAD_PROGRESS_UPLOADING: number = 30;
const UPLOAD_PROGRESS_COMPLETING: number = 70;
const UPLOAD_PROGRESS_DONE: number = 100;

const ALLOWED_TYPES: Set<string> = new Set([
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

interface UseFileUploadResult {
  isUploading: boolean;
  uploadProgress: number;
  handleUpload: (file: File) => Promise<void>;
  lastUploadId: string | null;
}

function validateFile(
  file: File,
  t: ReturnType<typeof useTranslation<['attachments']>>['t'],
): boolean {
  if (file.size > MAX_FILE_SIZE_BYTES) {
    toast.error(t('attachments:validation.fileTooLarge', { max: MAX_FILE_SIZE_MB }));
    return false;
  }
  if (!ALLOWED_TYPES.has(file.type)) {
    toast.error(t('attachments:validation.invalidType', { type: file.type }));
    return false;
  }
  return true;
}

/**
 * Encapsulates the multi-step S3 upload flow (initiate, upload, complete)
 * with progress tracking and validation.
 */
function useFileUpload(onComplete?: (uploadId: string) => void): UseFileUploadResult {
  const { t } = useTranslation(['attachments']);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [lastUploadId, setLastUploadId] = useState<string | null>(null);

  const initiateMutation = useInitiateUpload();
  const completeMutation = useCompleteUpload();

  const handleUpload = async (file: File): Promise<void> => {
    if (!validateFile(file, t)) {
      return;
    }

    setIsUploading(true);
    setUploadProgress(UPLOAD_PROGRESS_INITIATED);

    try {
      const initResponse = await initiateMutation.mutateAsync({
        body: {
          filename: file.name,
          content_type: file.type,
          file_size: file.size,
        },
      });

      if (!initResponse) {
        throw new Error('Upload initiation failed: no response received');
      }

      setUploadProgress(UPLOAD_PROGRESS_UPLOADING);
      await uploadToStorage(initResponse.upload_url, initResponse.upload_headers, file);
      setUploadProgress(UPLOAD_PROGRESS_COMPLETING);

      await completeMutation.mutateAsync({
        params: { path: { upload_id: initResponse.upload_id } },
        body: {
          filename: file.name,
          content_type: file.type,
          file_size: file.size,
        },
      });

      setUploadProgress(UPLOAD_PROGRESS_DONE);
      setLastUploadId(initResponse.upload_id);
      toast.success(t('attachments:upload.success'));
      onComplete?.(initResponse.upload_id);
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t('attachments:validation.uploadFailed', { filename: file.name, reason })
          : t('attachments:validation.uploadFailedFallback'),
      );
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  return { isUploading, uploadProgress, handleUpload, lastUploadId };
}

async function uploadToStorage(
  url: string,
  uploadHeaders: Record<string, string>,
  file: File,
): Promise<void> {
  const response = await fetch(url, {
    method: 'PUT',
    body: file,
    headers: { ...uploadHeaders, 'Content-Type': file.type },
  });
  if (!response.ok) {
    throw new Error('Upload failed');
  }
}

export { useFileUpload };
