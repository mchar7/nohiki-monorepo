import { type JSX, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSwipeToDismiss } from '@/shared/lib/index.ts';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/shared/ui/alert-dialog.tsx';
import { Separator } from '@/shared/ui/separator.tsx';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/shared/ui/sheet.tsx';
import { ExportJSON } from './DatasetForm/ExportJSON.tsx';
import { ImportJSON } from './DatasetForm/ImportJSON.tsx';

interface EditorModalsProps {
  showImportModal: boolean;
  showExportModal: boolean;
  showUnsavedDialog: boolean;
  currentDatasetId?: string | undefined;
  onImportModalChange: (open: boolean) => void;
  onExportModalChange: (open: boolean) => void;
  onUnsavedDialogChange: (open: boolean) => void;
  onConfirmNavigation: () => void;
  onCancelNavigation: () => void;
}

export function EditorModals({
  showImportModal,
  showExportModal,
  showUnsavedDialog,
  currentDatasetId,
  onImportModalChange,
  onExportModalChange,
  onUnsavedDialogChange,
  onConfirmNavigation,
  onCancelNavigation,
}: Readonly<EditorModalsProps>): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const importRef = useRef<HTMLDivElement>(null);
  const exportRef = useRef<HTMLDivElement>(null);

  const handleImportClose = (): void => {
    onImportModalChange(false);
  };

  const handleExportClose = (): void => {
    onExportModalChange(false);
  };

  useSwipeToDismiss({
    ref: importRef,
    onDismiss: handleImportClose,
    direction: 'right',
    enabled: showImportModal,
  });

  useSwipeToDismiss({
    ref: exportRef,
    onDismiss: handleExportClose,
    direction: 'right',
    enabled: showExportModal,
  });

  return (
    <>
      {/* Import Modal */}
      <Sheet open={showImportModal} onOpenChange={onImportModalChange}>
        <SheetContent ref={importRef} className="w-150 sm:max-w-150">
          <SheetHeader>
            <SheetTitle>{t('modals.import.title')}</SheetTitle>
            <SheetDescription>{t('modals.import.description')}</SheetDescription>
          </SheetHeader>
          <Separator className="my-4" />
          <ImportJSON isOpen={showImportModal} onClose={handleImportClose} />
        </SheetContent>
      </Sheet>

      {/* Export Modal */}
      <Sheet open={showExportModal} onOpenChange={onExportModalChange}>
        <SheetContent ref={exportRef} className="w-150 sm:max-w-150">
          <SheetHeader>
            <SheetTitle>{t('modals.export.title')}</SheetTitle>
            <SheetDescription>{t('modals.export.description')}</SheetDescription>
          </SheetHeader>
          <Separator className="my-4" />
          <ExportJSON
            isOpen={showExportModal}
            onClose={handleExportClose}
            preselectedDatasets={currentDatasetId ? [currentDatasetId] : []}
          />
        </SheetContent>
      </Sheet>

      {/* Unsaved Changes Dialog */}
      <AlertDialog open={showUnsavedDialog} onOpenChange={onUnsavedDialogChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('modals.unsavedChanges.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('modals.unsavedChanges.description')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={onCancelNavigation}>
              {t('modals.unsavedChanges.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={onConfirmNavigation}>
              {t('modals.unsavedChanges.continue')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
