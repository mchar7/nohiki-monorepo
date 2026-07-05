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
  readonly profileName: string;
  readonly isPending: boolean;
  readonly onConfirm: () => void;
}

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  profileName,
  isPending,
  onConfirm,
}: DeleteConfirmDialogProps): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);
  const isMobile = useIsMobileLayout();

  const handleCancel = (): void => {
    onOpenChange(false);
  };

  if (isMobile) {
    return (
      <BottomSheet
        open={open}
        onOpenChange={onOpenChange}
        title={t('profiles:confirmDelete.title')}
        description={t('profiles:confirmDelete.description', { name: profileName })}
      >
        <div className="flex flex-col gap-2 pt-4">
          <Button variant="destructive" onClick={onConfirm} disabled={isPending}>
            {t('profiles:actions.delete')}
          </Button>
          <Button variant="outline" onClick={handleCancel} disabled={isPending}>
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
          <AlertDialogTitle>{t('profiles:confirmDelete.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('profiles:confirmDelete.description', { name: profileName })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isPending}>{t('common:actions.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isPending}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {t('profiles:actions.delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
