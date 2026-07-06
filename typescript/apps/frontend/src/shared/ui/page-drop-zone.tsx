import { Upload } from 'lucide-react';
import type { JSX } from 'react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import type { PageDropZoneProps } from './page-drop-zone.types.ts';

interface UseDragOverlayResult {
  readonly isDragOver: boolean;
  readonly handlers: {
    readonly onDragEnter: (e: React.DragEvent) => void;
    readonly onDragOver: (e: React.DragEvent) => void;
    readonly onDragLeave: (e: React.DragEvent) => void;
    readonly onDrop: (e: React.DragEvent) => void;
  };
}

function useDragOverlay(
  onDrop: (files: FileList) => void,
  disabled: boolean,
): UseDragOverlayResult {
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = useRef(0);

  const onDragEnter = (e: React.DragEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) {
      return;
    }
    dragCounterRef.current += 1;
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragOver(true);
    }
  };

  const onDragOver = (e: React.DragEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) {
      return;
    }
    e.dataTransfer.dropEffect = 'copy';
  };

  const onDragLeave = (e: React.DragEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragOver(false);
    if (disabled) {
      return;
    }
    const { files } = e.dataTransfer;
    if (files.length > 0) {
      onDrop(files);
    }
  };

  return { isDragOver, handlers: { onDragEnter, onDragOver, onDragLeave, onDrop: handleDrop } };
}

function DropOverlay(): JSX.Element {
  const { t } = useTranslation(['common']);

  return (
    <output
      className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-lg border-[3px] border-primary border-dashed bg-primary/10 backdrop-blur-[2px]"
      aria-label={t('common:a11y.fileDropZone')}
      data-testid="page-drop-zone-overlay"
    >
      <div className="flex flex-col items-center gap-3">
        <div className="rounded-full bg-primary/15 p-5">
          <Upload className="size-10 text-primary" aria-hidden="true" />
        </div>
        <p className="font-semibold text-lg text-primary">{t('common:dropZone.dropToUpload')}</p>
      </div>
    </output>
  );
}

/**
 * Full-page drag-and-drop zone that wraps page content.
 * Shows a prominent overlay when files are dragged over the page boundary.
 */
function PageDropZone({
  children,
  onDrop,
  className,
  disabled = false,
}: PageDropZoneProps): JSX.Element {
  const { isDragOver, handlers } = useDragOverlay(onDrop, disabled);

  return (
    <div className={cn('relative', className)} {...handlers}>
      {children}
      {isDragOver ? <DropOverlay /> : null}
    </div>
  );
}

export { PageDropZone };
