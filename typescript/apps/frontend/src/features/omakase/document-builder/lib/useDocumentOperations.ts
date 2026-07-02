import { useMutation } from '@tanstack/react-query';
import { useRef } from 'react';
import { awaitDocumentReady } from '@/entities/document';
import { fetchClient } from '@/shared/api/index.ts';
import { logger } from '@/shared/lib/index.ts';
import { useDownloadDocument } from '../api/hooks.ts';

/** Builds a cache key from template ID and data. */
function buildCacheKey(templateId: string, data: Record<string, unknown>): string {
  return `${templateId}-${JSON.stringify(data)}`;
}

/** Validates that a template version ID is present, throwing otherwise. */
function requireTemplateVersionId(id: string | undefined): asserts id is string {
  if (!id) {
    throw new Error('Template version ID is required');
  }
}

/** Generates HTML content by posting a generation request and polling for the result. */
async function generateHtmlContent(
  options: DocumentOperationOptions,
  htmlCache: Map<string, string>,
): Promise<string> {
  const { template_version_id, data } = options;
  requireTemplateVersionId(template_version_id);

  logger.info('HTML Generation Request:', {
    templateVersionId: template_version_id,
    dataKeys: Object.keys(data),
  });

  const { data: response, error } = await fetchClient.POST('/api/v1/documents/generate', {
    body: { template_version_id, data, output_format: 'html' },
  });
  if (error) {
    throw error;
  }

  const { downloadUrl } = await awaitDocumentReady(response.request_id);
  const htmlResponse = await fetch(downloadUrl);
  if (!htmlResponse.ok) {
    throw new Error(`Generated document fetch failed with status ${htmlResponse.status}`);
  }
  const htmlContent = await htmlResponse.text();

  htmlCache.set(buildCacheKey(template_version_id, data), htmlContent);

  logger.info('HTML Generation Success:', {
    templateVersionId: template_version_id,
    contentLength: htmlContent.length,
  });

  return htmlContent;
}

/** Generates an image by posting a generation request and polling for the download URL. */
async function generateImageContent(options: DocumentOperationOptions): Promise<string> {
  const { template_version_id, data } = options;
  requireTemplateVersionId(template_version_id);

  logger.info('Image Generation Request:', {
    templateVersionId: template_version_id,
    dataKeys: Object.keys(data),
  });

  const { data: response, error } = await fetchClient.POST('/api/v1/documents/generate', {
    body: { template_version_id, data, output_format: 'png' },
  });
  if (error) {
    throw error;
  }

  const { downloadUrl, status } = await awaitDocumentReady(response.request_id);

  logger.info('Image Generation Success:', {
    templateVersionId: template_version_id,
    requestId: response.request_id,
    status,
  });
  return downloadUrl;
}

interface DocumentOperationOptions {
  template_version_id: string;
  data: Record<string, unknown>;
  filename?: string;
}

interface UseDocumentOperationsReturn {
  isGeneratingPreview: boolean;
  isGeneratingImage: boolean;
  isDownloadingPdf: boolean;
  generateHtml: (options: DocumentOperationOptions) => Promise<string>;
  generateImage: (options: DocumentOperationOptions) => Promise<string>;
  downloadPdf: (options: DocumentOperationOptions) => Promise<void>;
  cacheHtmlData: (templateId: string, data: Record<string, unknown>) => void;
  getCachedHtml: (templateId: string, data: Record<string, unknown>) => string | null;
}

/** Performs a PDF download with validation and logging. */
async function executePdfDownload(
  options: DocumentOperationOptions,
  downloadMutation: ReturnType<typeof useDownloadDocument>,
): Promise<void> {
  requireTemplateVersionId(options.template_version_id);
  logger.info('PDF Download Request:', {
    templateVersionId: options.template_version_id,
    dataKeys: Object.keys(options.data),
    filename: options.filename,
  });
  await downloadMutation.mutateAsync({
    template_version_id: options.template_version_id,
    data: options.data,
    output_format: 'pdf',
    filename: options.filename ?? 'document.pdf',
  });
  logger.info('PDF Download Success');
}

export function useDocumentOperations(): UseDocumentOperationsReturn {
  const downloadDocumentMutation = useDownloadDocument();
  const htmlCacheRef = useRef(new Map<string, string>());

  const cacheHtmlData = (templateId: string, data: Record<string, unknown>) =>
    htmlCacheRef.current.set(buildCacheKey(templateId, data), '');
  const getCachedHtml = (templateId: string, data: Record<string, unknown>) =>
    htmlCacheRef.current.get(buildCacheKey(templateId, data)) ?? null;

  const generateHtmlMutation = useMutation({
    mutationFn: (options: DocumentOperationOptions) =>
      generateHtmlContent(options, htmlCacheRef.current),
  });
  const generateImageMutation = useMutation({ mutationFn: generateImageContent });

  return {
    isGeneratingPreview: generateHtmlMutation.isPending,
    isGeneratingImage: generateImageMutation.isPending,
    isDownloadingPdf: downloadDocumentMutation.isPending,
    generateHtml: async (options: DocumentOperationOptions) =>
      generateHtmlMutation.mutateAsync(options),
    generateImage: async (options: DocumentOperationOptions) =>
      generateImageMutation.mutateAsync(options),
    downloadPdf: async (options: DocumentOperationOptions) =>
      executePdfDownload(options, downloadDocumentMutation),
    cacheHtmlData,
    getCachedHtml,
  };
}
