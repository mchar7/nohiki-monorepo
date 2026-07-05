import { Loader2, Save, X } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';

interface ProfileEditActionsProps {
  readonly isPending: boolean;
  readonly onCancel: () => void;
}

export function ProfileEditActions({ isPending, onCancel }: ProfileEditActionsProps): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);

  return (
    <div className="flex justify-end gap-3">
      <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>
        <X className="mr-2 size-4" />
        {t('common:actions.cancel')}
      </Button>
      <Button type="submit" disabled={isPending}>
        {isPending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Save className="mr-2 size-4" />
        )}
        {isPending ? t('profiles:pages.detail.submitting') : t('profiles:actions.save')}
      </Button>
    </div>
  );
}
