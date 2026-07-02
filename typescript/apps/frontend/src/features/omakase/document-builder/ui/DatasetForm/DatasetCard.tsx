import { cn } from '@shared/lib/index.ts';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
} from '@shared/ui/index.ts';
import { Calendar } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import type { Dataset } from '../../model/index.ts';
import { CardActionsMenu } from './CardActionsMenu.tsx';

interface DatasetCardProps {
  dataset: Dataset;
  template?: TemplateFamilyResponse | undefined;
  onEdit?: ((dataset: Dataset) => void) | undefined;
  onDelete?: ((dataset: Dataset) => void) | undefined;
  onDuplicate?: ((dataset: Dataset) => void) | undefined;
  onDownload?: ((dataset: Dataset) => void) | undefined;
  onRename?: ((dataset: Dataset, newName: string) => void) | undefined;
  isSelected?: boolean | undefined;
  'aria-label'?: string | undefined;
}

interface RenameDialogProps {
  readonly dataset: Dataset;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onRename: (dataset: Dataset, newName: string) => void;
}

function RenameDialog({ dataset, open, onOpenChange, onRename }: RenameDialogProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const raw = formData.get('name');
    const trimmed = typeof raw === 'string' ? raw.trim() : '';
    if (trimmed && trimmed !== dataset.name) {
      onRename(dataset, trimmed);
    }
    onOpenChange(false);
  };

  const handleCancelClick = (): void => {
    onOpenChange(false);
  };

  // Portal remount on each open resets defaultValue automatically;
  // uncontrolled avoids per-keystroke re-renders of the entire dialog.
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('datasets.card.rename')}</DialogTitle>
          <DialogDescription className="sr-only">{t('datasets.card.editName')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <Input
            name="name"
            defaultValue={dataset.name}
            autoFocus={true}
            aria-label={t('datasets.card.editName')}
            className="my-4"
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleCancelClick}>
              {t('datasets.card.cancel')}
            </Button>
            <Button type="submit">{t('datasets.card.save')}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DatasetCardFooter({
  dataset,
  cachedLabel,
  createdTitle,
}: {
  readonly dataset: Dataset;
  readonly cachedLabel: string;
  readonly createdTitle: string;
}): JSX.Element {
  return (
    <CardContent className="pt-0">
      <div className="flex items-center gap-4 text-muted-foreground text-sm">
        <div className="flex items-center gap-1" title={createdTitle}>
          <Calendar className="size-3" aria-hidden="true" />
          <span>{new Date(dataset.createdAt).toLocaleDateString()}</span>
        </div>
        {dataset.cachedHtmlData ? (
          <Badge variant="outline" className="text-xs">
            {cachedLabel}
          </Badge>
        ) : null}
      </div>
    </CardContent>
  );
}

function DatasetCard({
  dataset,
  template,
  onEdit,
  onDelete,
  onDuplicate,
  onDownload,
  onRename,
  isSelected = false,
  'aria-label': ariaLabel,
}: DatasetCardProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const handleCardClick = (): void => onEdit?.(dataset);
  const handleStopPropagation = (e: React.MouseEvent): void => e.stopPropagation();
  const handleShowRename = (): void => setShowRenameDialog(true);
  const createdDate = new Date(dataset.createdAt).toLocaleDateString();
  const cardAriaLabel =
    ariaLabel ??
    (template
      ? t('omakase.editor:datasets.card.ariaLabelWithTemplate', {
          name: dataset.name,
          template: template.display_name || t('common:unavailable'),
          date: createdDate,
        })
      : t('omakase.editor:datasets.card.ariaLabel', { name: dataset.name, date: createdDate }));

  return (
    <>
      <Card
        className={cn(
          'relative transition-all hover:shadow-md',
          isSelected && 'bg-primary/5 ring-2 ring-primary',
        )}
      >
        <button
          type="button"
          className="w-full cursor-pointer text-left focus-visible:outline-none"
          onClick={handleCardClick}
          aria-label={cardAriaLabel}
          aria-pressed={isSelected}
        >
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1 pr-10">
                <CardTitle className="truncate text-lg" title={dataset.name}>
                  {dataset.name}
                </CardTitle>
                {template ? (
                  <CardDescription className="mt-1 flex items-center gap-1">
                    <Badge variant="secondary" className="text-xs">
                      {template.display_name || t('common:unavailable')}
                    </Badge>
                  </CardDescription>
                ) : null}
              </div>
            </div>
          </CardHeader>
          <DatasetCardFooter
            dataset={dataset}
            cachedLabel={t('omakase.editor:datasets.card.htmlCached')}
            createdTitle={t('omakase.editor:datasets.card.created', {
              date: Intl.DateTimeFormat(undefined, {
                dateStyle: 'short',
                timeStyle: 'medium',
              }).format(new Date(dataset.createdAt)),
            })}
          />
        </button>
        <div className="absolute top-6 right-6">
          <CardActionsMenu
            dataset={dataset}
            onStopPropagation={handleStopPropagation}
            onEdit={onEdit}
            onRename={handleShowRename}
            onDuplicate={onDuplicate}
            onDownload={onDownload}
            onDelete={onDelete}
          />
        </div>
      </Card>

      {onRename ? (
        <RenameDialog
          dataset={dataset}
          open={showRenameDialog}
          onOpenChange={setShowRenameDialog}
          onRename={onRename}
        />
      ) : null}
    </>
  );
}

export { DatasetCard };
