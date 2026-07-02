import { Upload } from 'lucide-react';
import type { JSX } from 'react';
import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn, useIsMobileLayout } from '@/shared/lib';
import { BottomSheet } from '@/shared/ui/bottom-sheet.tsx';
import { Button } from '@/shared/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/shared/ui/dialog.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { Progress } from '@/shared/ui/progress.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import {
  DOCUMENT_CATEGORIES,
  type DocumentCategory,
  inferCategory,
  saveCategory,
} from '../lib/categorize.ts';
import { useFileUpload } from '../lib/useFileUpload.ts';

const MAX_FILE_SIZE_MB: number = 10;

interface UploadDialogProps {
  readonly onSuccess?: () => void;
}

function UploadDialog({ onSuccess }: UploadDialogProps): JSX.Element {
  const isMobile = useIsMobileLayout();
  const [open, setOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<DocumentCategory>('other');
  const categoryRef = useRef<DocumentCategory>('other');
  const categoryId = useId();

  const updateCategory = (category: DocumentCategory): void => {
    setSelectedCategory(category);
    categoryRef.current = category;
  };

  const onComplete = (uploadId: string): void => {
    saveCategory(uploadId, categoryRef.current);
    setOpen(false);
    updateCategory('other');
    onSuccess?.();
  };

  const { isUploading, uploadProgress, handleUpload } = useFileUpload(onComplete);

  const startUpload = (file: File): void => {
    updateCategory(inferCategory(file.name));
    handleUpload(file).catch(() => undefined);
  };

  const handleDrop = (e: React.DragEvent): void => {
    e.preventDefault();
    setIsDragging(false);
    const [file] = e.dataTransfer.files;
    if (file) {
      startUpload(file);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const file = e.target.files?.[0];
    if (file) {
      startUpload(file);
    }
  };

  return (
    <UploadShell open={open} onOpenChange={setOpen} isMobile={isMobile}>
      <UploadContent
        isDragging={isDragging}
        isUploading={isUploading}
        uploadProgress={uploadProgress}
        selectedCategory={selectedCategory}
        categoryId={categoryId}
        onCategoryChange={updateCategory}
        onDragEnter={(): void => setIsDragging(true)}
        onDragLeave={(): void => setIsDragging(false)}
        onDrop={handleDrop}
        onFileSelect={handleFileSelect}
      />
    </UploadShell>
  );
}

interface UploadShellProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly isMobile: boolean;
  readonly children: React.ReactNode;
}

function UploadShell({ open, onOpenChange, isMobile, children }: UploadShellProps): JSX.Element {
  const { t } = useTranslation(['attachments']);

  if (isMobile) {
    return (
      <>
        <Button onClick={() => onOpenChange(true)}>
          <Upload className="mr-2 size-4" aria-hidden="true" />
          {t('attachments:actions.upload')}
        </Button>
        <BottomSheet
          open={open}
          onOpenChange={onOpenChange}
          title={t('attachments:upload.title')}
          description={t('attachments:upload.description')}
        >
          {children}
        </BottomSheet>
      </>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild={true}>
        <Button>
          <Upload className="mr-2 size-4" aria-hidden="true" />
          {t('attachments:actions.upload')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('attachments:upload.title')}</DialogTitle>
          <DialogDescription>{t('attachments:upload.description')}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

interface UploadContentProps {
  readonly isDragging: boolean;
  readonly isUploading: boolean;
  readonly uploadProgress: number;
  readonly selectedCategory: DocumentCategory;
  readonly categoryId: string;
  readonly onCategoryChange: (category: DocumentCategory) => void;
  readonly onDragEnter: () => void;
  readonly onDragLeave: () => void;
  readonly onDrop: (e: React.DragEvent) => void;
  readonly onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

function UploadContent({
  isDragging,
  isUploading,
  uploadProgress,
  selectedCategory,
  categoryId,
  onCategoryChange,
  onDragEnter,
  onDragLeave,
  onDrop,
  onFileSelect,
}: UploadContentProps): JSX.Element {
  const { t } = useTranslation(['attachments']);

  return (
    <>
      <DropZone
        isDragging={isDragging}
        isUploading={isUploading}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onFileSelect={onFileSelect}
      />

      {isUploading ? (
        <div className="space-y-4">
          <CategorySelector id={categoryId} value={selectedCategory} onChange={onCategoryChange} />
          <div className="space-y-2">
            <Progress value={uploadProgress} />
            <p className="text-center text-muted-foreground text-sm">
              {t('attachments:upload.uploading')}
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}

interface DropZoneProps {
  readonly isDragging: boolean;
  readonly isUploading: boolean;
  readonly onDragEnter: () => void;
  readonly onDragLeave: () => void;
  readonly onDrop: (e: React.DragEvent) => void;
  readonly onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

function DropZone({
  isDragging,
  isUploading,
  onDragEnter,
  onDragLeave,
  onDrop,
  onFileSelect,
}: DropZoneProps): JSX.Element {
  const { t } = useTranslation(['attachments']);
  const inputRef = useRef<HTMLInputElement>(null);

  const openFilePicker = (): void => {
    inputRef.current?.click();
  };

  const handleDragEnter = (e: React.DragEvent): void => {
    e.preventDefault();
    onDragEnter();
  };

  const handleDragOver = (e: React.DragEvent): void => {
    e.preventDefault();
  };

  const handleDragLeave = (e: React.DragEvent): void => {
    e.preventDefault();
    onDragLeave();
  };

  const dropzoneText = isDragging
    ? t('attachments:upload.dropzoneActive')
    : t('attachments:upload.dropzone');

  return (
    <>
      <button
        type="button"
        className={cn(
          'block w-full cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-all duration-200',
          isDragging
            ? 'scale-[1.01] border-primary bg-primary/10 shadow-md ring-2 ring-primary/20'
            : 'border-muted-foreground/25 bg-transparent',
          isUploading && 'pointer-events-none opacity-50',
        )}
        onClick={openFilePicker}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={onDrop}
        disabled={isUploading}
      >
        <Upload className="mx-auto mb-4 size-12 text-muted-foreground" aria-hidden="true" />
        <p className="mb-2 text-muted-foreground">{dropzoneText}</p>
        <span className="inline-flex">
          <span className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-input bg-background px-4 py-2 font-medium text-sm shadow-xs">
            {t('attachments:upload.browse')}
          </span>
        </span>
        <p className="mt-4 text-muted-foreground text-xs">
          {t('attachments:upload.allowedTypes', { size: MAX_FILE_SIZE_MB })}
        </p>
      </button>
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept=".pdf,.doc,.docx,.txt"
        aria-label={t('attachments:upload.browse')}
        onChange={onFileSelect}
        disabled={isUploading}
        tabIndex={-1}
      />
    </>
  );
}

interface CategorySelectorProps {
  readonly id: string;
  readonly value: DocumentCategory;
  readonly onChange: (category: DocumentCategory) => void;
}

function CategorySelector({ id, value, onChange }: CategorySelectorProps): JSX.Element {
  const { t } = useTranslation(['attachments']);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{t('attachments:category.label')}</Label>
      <Select value={value} onValueChange={(v: string): void => onChange(v as DocumentCategory)}>
        <SelectTrigger id={id} className="w-full" aria-label={t('attachments:category.label')}>
          <SelectValue placeholder={t('attachments:category.selectPlaceholder')} />
        </SelectTrigger>
        <SelectContent>
          {DOCUMENT_CATEGORIES.map((cat) => (
            <SelectItem key={cat} value={cat}>
              {t(`attachments:category.${cat}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export { UploadDialog };
