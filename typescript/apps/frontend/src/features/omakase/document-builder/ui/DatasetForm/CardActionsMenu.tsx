import { Button } from '@shared/ui/button.tsx';
import {
  ResponsiveMenu,
  ResponsiveMenuItem,
  ResponsiveMenuSeparator,
} from '@shared/ui/responsive-menu.tsx';
import { Copy, Download, Edit, MoreHorizontal, Trash2 } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Dataset } from '../../model/index.ts';

interface CardActionsMenuProps {
  readonly dataset: Dataset;
  readonly onStopPropagation: (e: React.MouseEvent) => void;
  readonly onEdit?: ((dataset: Dataset) => void) | undefined;
  readonly onRename: () => void;
  readonly onDuplicate?: ((dataset: Dataset) => void) | undefined;
  readonly onDownload?: ((dataset: Dataset) => void) | undefined;
  readonly onDelete?: ((dataset: Dataset) => void) | undefined;
}

/** Responsive actions menu: DropdownMenu on desktop, BottomSheet on mobile.
 *  stopPropagation is applied to the trigger to prevent card click events. */
function CardActionsMenu({
  dataset,
  onStopPropagation,
  onEdit,
  onRename,
  onDuplicate,
  onDownload,
  onDelete,
}: CardActionsMenuProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <ResponsiveMenu
      open={menuOpen}
      onOpenChange={setMenuOpen}
      title={t('datasets.card.actions')}
      trigger={
        <Button
          variant="ghost"
          size="sm"
          className="size-8 p-0"
          onClick={onStopPropagation}
          aria-label={t('common:a11y.more')}
        >
          <MoreHorizontal className="size-4" aria-hidden="true" />
        </Button>
      }
    >
      <ResponsiveMenuItem
        icon={<Edit className="size-4" aria-hidden="true" />}
        onClick={() => onEdit?.(dataset)}
      >
        {t('datasets.card.editDataset')}
      </ResponsiveMenuItem>
      <ResponsiveMenuItem icon={<Edit className="size-4" aria-hidden="true" />} onClick={onRename}>
        {t('datasets.card.rename')}
      </ResponsiveMenuItem>
      <ResponsiveMenuItem
        icon={<Copy className="size-4" aria-hidden="true" />}
        onClick={() => onDuplicate?.(dataset)}
      >
        {t('datasets.card.duplicate')}
      </ResponsiveMenuItem>
      <ResponsiveMenuItem
        icon={<Download className="size-4" aria-hidden="true" />}
        onClick={() => onDownload?.(dataset)}
      >
        {t('datasets.card.downloadPdf')}
      </ResponsiveMenuItem>
      <ResponsiveMenuSeparator />
      <ResponsiveMenuItem
        icon={<Trash2 className="size-4" aria-hidden="true" />}
        variant="destructive"
        onClick={() => onDelete?.(dataset)}
      >
        {t('datasets.card.delete')}
      </ResponsiveMenuItem>
    </ResponsiveMenu>
  );
}

export { CardActionsMenu };
