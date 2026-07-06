import { Bookmark, BookmarkCheck } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './button.tsx';
import type { SaveToggleProps } from './save-toggle.types.ts';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip.tsx';

/** Bookmark icon button that toggles between saved and unsaved states. */
function SaveToggle({
  isSaved,
  onToggle,
  disabled = false,
  disabledTooltip,
}: SaveToggleProps): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const label = isSaved ? t('actions.unsave') : t('actions.save');

  if (disabled && disabledTooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild={true}>
          <span className="inline-flex">
            <Button variant="ghost" size="icon" disabled={true} aria-label={label}>
              <Bookmark className="size-4" aria-hidden="true" />
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>{disabledTooltip}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      disabled={disabled}
      onClick={onToggle}
      aria-label={label}
      className={isSaved ? 'text-primary' : 'text-muted-foreground hover:text-primary'}
    >
      {isSaved ? (
        <BookmarkCheck className="size-4" aria-hidden="true" />
      ) : (
        <Bookmark className="size-4" aria-hidden="true" />
      )}
    </Button>
  );
}

export { SaveToggle };
