import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
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
import { BottomSheet } from '@/shared/ui/bottom-sheet.tsx';
import { Button } from '@/shared/ui/button.tsx';

interface DeleteConfirmDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly filename: string;
  readonly onConfirm: () => void;
  readonly isDeleting: boolean;
}

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  filename,
  onConfirm,
  isDeleting,
}: DeleteConfirmDialogProps): JSX.Element {
  const { t } = useTranslation(['attachments', 'common']);
  const isMobile = useIsMobileLayout();
  const deleteActionLabel = isDeleting ? t('common:states.processing') : t('common:actions.delete');

  const handleCancel = (): void => {
    onOpenChange(false);
  };

  if (isMobile) {
    return (
      <BottomSheet
        open={open}
        onOpenChange={onOpenChange}
        title={t('attachments:confirmDelete.title')}
        description={t('attachments:confirmDelete.description', { name: filename })}
      >
        <div className="flex flex-col gap-2 pt-4">
          <Button variant="destructive" onClick={onConfirm} disabled={isDeleting}>
            {deleteActionLabel}
          </Button>
          <Button variant="outline" onClick={handleCancel} disabled={isDeleting}>
            {t('common:actions.cancel')}
          </Button>
        </div>
      </BottomSheet>
    );
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('attachments:confirmDelete.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('attachments:confirmDelete.description', { name: filename })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>{t('common:actions.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isDeleting}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {deleteActionLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
