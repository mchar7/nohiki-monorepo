import { X } from 'lucide-react';
import { type JSX, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSwipeToDismiss } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/shared/ui/sheet.tsx';
import type { PageSize, TemplateData } from '../model/index.ts';
import { DynamicPreview } from './DynamicPreview.tsx';

interface PreviewSheetProps {
  /** Whether the sheet is open */
  readonly open: boolean;
  /** Callback when sheet should close */
  readonly onOpenChange: (open: boolean) => void;
  /** Page size for preview rendering */
  readonly pageSize: PageSize;
  /** Template version ID for preview (optional for unsaved templates) */
  readonly templateVersionId?: string | undefined;
  /** Template data for preview */
  readonly templateData?: TemplateData | undefined;
  /** Error handler */
  readonly onError?: ((error: string) => void) | undefined;
}

/**
 * A full-screen sheet component for displaying document preview on mobile devices.
 * Wraps the DynamicPreview component in a Sheet for modal presentation.
 */
export function PreviewSheet({
  open,
  onOpenChange,
  pageSize,
  templateVersionId,
  templateData,
  onError,
}: PreviewSheetProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  const descriptionId = useId();
  const contentRef = useRef<HTMLDivElement>(null);

  const handleClose = (): void => {
    onOpenChange(false);
  };

  useSwipeToDismiss({
    ref: contentRef,
    onDismiss: handleClose,
    direction: 'down',
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        ref={contentRef}
        side="bottom"
        className="h-[85vh] rounded-t-xl p-0"
        aria-describedby={descriptionId}
        hideCloseButton={true}
      >
        <SheetHeader className="sr-only">
          <SheetTitle>{t('title')}</SheetTitle>
          <SheetDescription id={descriptionId}>{t('mobilePreview.description')}</SheetDescription>
        </SheetHeader>

        {/* Close button - floats over the preview header */}
        <div className="absolute top-3 right-3 z-10">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 bg-background/80 backdrop-blur-sm hover:bg-background"
            onClick={handleClose}
            aria-label={t('mobilePreview.close')}
          >
            <X className="size-4" />
          </Button>
        </div>

        {/* Preview content - uses DynamicPreview's header with zoom controls */}
        <div className="h-[85vh]">
          <DynamicPreview
            pageSize={pageSize}
            templateVersionId={templateVersionId}
            templateData={templateData}
            onError={onError}
            className="h-full"
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
