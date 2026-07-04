import { AlertTriangle } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { TOAST_ERROR, TOAST_SUCCESS } from '@/shared/lib';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/shared/ui/alert-dialog.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { useDeleteAccount } from '../api/index.ts';

const CONFIRM_TEXT = 'DELETE';

function DeleteAccountSection(): JSX.Element {
  const { t } = useTranslation(['account', 'common']);
  const deleteMutation = useDeleteAccount();
  const [confirmText, setConfirmText] = useState('');
  const [open, setOpen] = useState(false);

  const canDelete = confirmText === CONFIRM_TEXT;

  const handleConfirmTextChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    setConfirmText(e.target.value);
  };

  const handleDelete = async (): Promise<void> => {
    if (!canDelete) {
      return;
    }

    try {
      await deleteMutation.mutateAsync({});
      toast.success(t(TOAST_SUCCESS.ACCOUNT_DELETED));
    } catch {
      toast.error(t(TOAST_ERROR.ACCOUNT_DELETE_FAILED));
    }
  };

  const handleOpenChange = (isOpen: boolean): void => {
    setOpen(isOpen);
    if (!isOpen) {
      setConfirmText('');
    }
  };

  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="size-5" aria-hidden="true" />
          {t('account:sections.dangerZone.title')}
        </CardTitle>
        <CardDescription>{t('account:sections.dangerZone.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <DeleteAccountContent />
        <AlertDialog open={open} onOpenChange={handleOpenChange}>
          <AlertDialogTrigger asChild={true}>
            <Button variant="destructive">{t('account:actions.deleteAccount')}</Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('account:deleteAccount.confirmTitle')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('account:deleteAccount.confirmDescription')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className="py-4">
              <p className="mb-2 text-muted-foreground text-sm">
                {t('account:deleteAccount.typeToConfirm')}
              </p>
              <Input
                value={confirmText}
                onChange={handleConfirmTextChange}
                placeholder={t('account:deleteAccount.placeholder')}
              />
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleteMutation.isPending}>
                {t('account:deleteAccount.cancelButton')}
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={handleDelete}
                disabled={!canDelete || deleteMutation.isPending}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                <DeleteActionLabel isPending={deleteMutation.isPending} />
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}

function DeleteActionLabel({ isPending }: { readonly isPending: boolean }): JSX.Element {
  const { t } = useTranslation(['account']);
  if (isPending) {
    return <>{t('account:deleteAccount.deleting')}</>;
  }
  return <>{t('account:deleteAccount.confirmButton')}</>;
}

function DeleteAccountContent(): JSX.Element {
  const { t } = useTranslation(['account']);

  return (
    <div className="mb-4">
      <p className="text-muted-foreground text-sm">{t('account:deleteAccount.description')}</p>
      <p className="mt-2 font-medium text-destructive text-sm">
        {t('account:deleteAccount.warning')}
      </p>
    </div>
  );
}

export { DeleteAccountSection };
