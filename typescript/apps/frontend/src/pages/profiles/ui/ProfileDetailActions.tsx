import { Edit2, MoreVertical, Trash2 } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';
import {
  ResponsiveMenu,
  ResponsiveMenuItem,
  ResponsiveMenuSeparator,
} from '@/shared/ui/responsive-menu.tsx';

interface ProfileDetailActionsProps {
  readonly onEdit: () => void;
  readonly onDelete: () => void;
}

function ProfileDetailActions({ onEdit, onDelete }: ProfileDetailActionsProps): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);
  const [open, setOpen] = useState(false);

  return (
    <ResponsiveMenu
      open={open}
      onOpenChange={setOpen}
      title={t('common:a11y.more')}
      trigger={
        <Button variant="outline" size="icon">
          <MoreVertical className="size-4" />
          <span className="sr-only">{t('common:a11y.more')}</span>
        </Button>
      }
    >
      <ResponsiveMenuItem icon={<Edit2 className="size-4" />} onClick={onEdit}>
        {t('profiles:actions.edit')}
      </ResponsiveMenuItem>
      <ResponsiveMenuSeparator />
      <ResponsiveMenuItem
        icon={<Trash2 className="size-4" />}
        variant="destructive"
        onClick={onDelete}
      >
        {t('profiles:actions.delete')}
      </ResponsiveMenuItem>
    </ResponsiveMenu>
  );
}

export { ProfileDetailActions };
