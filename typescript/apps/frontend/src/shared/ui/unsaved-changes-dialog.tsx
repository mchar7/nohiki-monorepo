import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from './alert-dialog.tsx';
import type { UnsavedChangesDialogProps } from './unsaved-changes-dialog.types.ts';

/**
 * Modal dialog prompting the user to confirm discarding unsaved form changes
 * before navigating away. Uses common:unsavedChanges.* i18n keys.
 *
 * Pair with useUnsavedChanges hook:
 * - open={blocker.status === 'blocked'}
 * - onConfirm={blocker.proceed}
 * - onCancel={blocker.reset}
 *
 * Note: No onOpenChange is wired; the blocker controls open state via
 * proceed()/reset() exclusively, preventing accidental dismiss via overlay click.
 * Callbacks are undefined when status is 'idle' (dialog is closed).
 */
function UnsavedChangesDialog({
  open,
  onConfirm,
  onCancel,
}: UnsavedChangesDialogProps): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <AlertDialog open={open}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('unsavedChanges.title')}</AlertDialogTitle>
          <AlertDialogDescription>{t('unsavedChanges.description')}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>{t('unsavedChanges.stay')}</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>{t('unsavedChanges.leave')}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export { UnsavedChangesDialog };
