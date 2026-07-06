import { Link } from '@tanstack/react-router';
import { ArrowLeft } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigationHistory } from '@/shared/lib/hooks/useNavigationHistory.ts';
import { Button } from '@/shared/ui/button.tsx';

interface PageHeaderProps {
  readonly title: string;
  readonly description?: string;
  /** Static parent route. Always required when a back button is shown. */
  readonly backTo?: string;
  /** When true, prefer browser history over the static `backTo` route.
   *  Falls back to `backTo` if the user has no internal navigation history
   *  (e.g. deep link). Requires `backTo` to be set. */
  readonly preferHistory?: boolean;
  readonly actions?: ReactNode;
}

/** Renders the back-navigation button based on history availability. */
function BackButton({
  backTo,
  preferHistory,
}: {
  readonly backTo: string;
  readonly preferHistory: boolean | undefined;
}): JSX.Element {
  const { t } = useTranslation('common');
  const { canGoBack, goBack } = useNavigationHistory();

  if (preferHistory === true && canGoBack) {
    return (
      <Button variant="ghost" size="icon" onClick={() => goBack(backTo)}>
        <ArrowLeft className="size-4" />
        <span className="sr-only">{t('actions.goBack')}</span>
      </Button>
    );
  }

  return (
    <Button variant="ghost" size="icon" asChild={true}>
      <Link to={backTo}>
        <ArrowLeft className="size-4" />
        <span className="sr-only">{t('actions.goBack')}</span>
      </Link>
    </Button>
  );
}

/**
 * Page-level header with optional back navigation, title, description, and action slot.
 *
 * When `preferHistory` is enabled and the user has internal navigation history,
 * the back button uses `globalThis.history.back()` (preserving scroll position).
 * Otherwise it falls back to a static `<Link>` to `backTo`.
 */
export function PageHeader({
  title,
  description,
  backTo,
  preferHistory,
  actions,
}: PageHeaderProps): JSX.Element {
  return (
    <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
      <div className="flex min-w-0 items-center gap-4">
        {backTo ? <BackButton backTo={backTo} preferHistory={preferHistory} /> : null}
        <div className="min-w-0">
          <h1 className="break-words font-bold text-2xl">{title}</h1>
          {description ? <p className="break-words text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? (
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{actions}</div>
      ) : null}
    </div>
  );
}
