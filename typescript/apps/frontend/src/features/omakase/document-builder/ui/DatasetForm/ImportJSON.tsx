import { Button } from '@shared/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@shared/ui/dialog.tsx';
import { AlertCircle, FileText, Upload } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useJsonImport } from '../../lib/useJsonImport.ts';

/** Maximum number of field names shown in the import preview */
const IMPORT_PREVIEW_FIELD_LIMIT: number = 5;

import type { DatasetData } from '../../model/index.ts';

interface ImportJsonProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly onImport?: (data: DatasetData) => void;
}

interface FileSelectContext {
  importJsonData: (jsonString: string) => {
    success: boolean;
    data?: DatasetData;
    errors?: string[];
  };
  setPreviewData: (data: DatasetData | null) => void;
  setError: (error: string | null) => void;
  t: (key: string) => string;
}

async function processFile(file: File, ctx: FileSelectContext): Promise<void> {
  ctx.setError(null);
  ctx.setPreviewData(null);
  try {
    const text = await file.text();
    const result = ctx.importJsonData(text);
    if (result.success && result.data) {
      ctx.setPreviewData(result.data);
    } else {
      ctx.setError(result.errors?.join(', ') || ctx.t('import.invalidData'));
    }
  } catch {
    ctx.setError(ctx.t('import.failedToReadFile'));
  }
}

function BrowseFilesButton({
  fileInputRef,
  label,
}: {
  readonly fileInputRef: React.RefObject<HTMLInputElement | null>;
  readonly label: string;
}): JSX.Element {
  const handleClick = (): void => {
    fileInputRef.current?.click();
  };

  return (
    <Button variant="outline" onClick={handleClick}>
      {label}
    </Button>
  );
}

function ErrorAlert({ message }: { readonly message: string }): JSX.Element {
  return (
    <div
      className="mt-4 rounded-lg border border-destructive/20 bg-destructive/10 p-4"
      role="alert"
      aria-atomic="true"
    >
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="size-5" aria-hidden="true" />
        <span className="font-medium">{message}</span>
      </div>
    </div>
  );
}

function ImportPreview({
  fieldNames,
  t,
}: {
  readonly fieldNames: string[];
  readonly t: (key: string, options?: Record<string, unknown>) => string;
}): JSX.Element {
  return (
    <output className="block space-y-4" aria-live="polite" aria-atomic="true">
      <span className="flex items-center gap-2 text-green-600">
        <FileText className="size-5" aria-hidden="true" />
        <span className="font-medium">{t('import.validDataFound')}</span>
      </span>
      <span className="block rounded-lg bg-muted p-4">
        <span className="mb-2 block font-medium">{t('import.preview')}</span>
        <span className="block text-muted-foreground text-sm">
          {t('import.fieldsFound', {
            count: fieldNames.length,
            fields: fieldNames.slice(0, IMPORT_PREVIEW_FIELD_LIMIT).join(', '),
          })}
          {fieldNames.length > IMPORT_PREVIEW_FIELD_LIMIT &&
            ` ${t('import.andMore', { count: fieldNames.length - IMPORT_PREVIEW_FIELD_LIMIT })}`}
        </span>
      </span>
    </output>
  );
}

export function ImportJSON({ isOpen, onClose, onImport }: ImportJsonProps): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [previewData, setPreviewData] = useState<DatasetData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { isValidating, importJsonData, clearValidation } = useJsonImport();

  const handleClose = (): void => {
    setPreviewData(null);
    setError(null);
    clearValidation();
    onClose();
  };

  const processSelectedFile = (file: File): Promise<void> =>
    processFile(file, { importJsonData, setPreviewData, setError, t });

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (file) {
      await processSelectedFile(file);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLButtonElement>): void => {
    e.preventDefault();
    const [file] = e.dataTransfer.files;
    if (file) {
      void processSelectedFile(file);
    }
  };

  const handleImport = (): void => {
    if (previewData) {
      onImport?.(previewData);
      handleClose();
    }
  };

  const fieldNames = previewData ? Object.keys(previewData) : [];

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('import.title')}</DialogTitle>
          <DialogDescription>{t('import.description')}</DialogDescription>
        </DialogHeader>

        <div className="p-6">
          {previewData ? (
            <ImportPreview fieldNames={fieldNames} t={t} />
          ) : (
            <div className="space-y-4">
              <button
                type="button"
                className="relative block w-full cursor-pointer rounded-lg border-2 border-muted-foreground/50 border-dashed p-8 text-center"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e: React.DragEvent<HTMLButtonElement>): void => e.preventDefault()}
                onDrop={handleDrop}
              >
                <div className="flex flex-col items-center gap-4">
                  <Upload className="size-12 text-muted-foreground" aria-hidden="true" />
                  <div>
                    <p className="font-medium text-lg">{t('import.dropzone')}</p>
                  </div>
                </div>
              </button>

              <div className="text-center">
                <p className="mb-2 text-muted-foreground">{t('import.dropzoneOr')}</p>
                <BrowseFilesButton fileInputRef={fileInputRef} label={t('import.browseFiles')} />
              </div>

              <input
                ref={fileInputRef}
                id="import-json-file"
                type="file"
                accept=".json"
                aria-label={t('import.browseFiles')}
                onChange={handleFileSelect}
                className="sr-only"
                tabIndex={-1}
              />
            </div>
          )}

          {error ? <ErrorAlert message={error} /> : null}

          {isValidating ? (
            <output className="mt-4 block text-center" aria-live="polite" aria-atomic="true">
              <div
                className="inline-block size-6 animate-spin rounded-full border-primary border-b-2"
                aria-hidden="true"
              />
              <p className="mt-2 text-muted-foreground">{t('import.validating')}</p>
            </output>
          ) : null}
        </div>

        <div className="flex justify-end gap-3 pt-4">
          <Button variant="outline" onClick={handleClose}>
            {t('actions.cancel')}
          </Button>
          <Button onClick={handleImport} disabled={!previewData || isValidating}>
            {t('import.importDataset')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
