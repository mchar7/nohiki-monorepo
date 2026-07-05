import { AlertCircle, AlertTriangle, Info } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui/badge.tsx';
import type { ExtendedValidationIssue } from '../model/index.ts';

interface ValidationBadgesProps {
  readonly errorCount: number;
  readonly warningCount: number;
}

function ValidationBadges({ errorCount, warningCount }: ValidationBadgesProps): JSX.Element | null {
  if (errorCount === 0 && warningCount === 0) {
    return null;
  }

  const errorLabel = errorCount === 1 ? 'error' : 'errors';
  const warningLabel = warningCount === 1 ? 'warning' : 'warnings';

  return (
    <div className="flex items-center gap-2">
      {errorCount > 0 ? (
        <Badge variant="destructive" className="gap-1 px-2 py-0.5">
          <AlertCircle className="size-3.5" aria-hidden="true" />
          <span className="xs:inline hidden">{`${errorCount} ${errorLabel}`}</span>
          <span className="xs:hidden">{errorCount}</span>
        </Badge>
      ) : null}
      {warningCount > 0 ? (
        <Badge
          variant="outline"
          className="gap-1 border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-amber-600 dark:text-amber-400"
        >
          <AlertTriangle className="size-3.5" aria-hidden="true" />
          <span className="xs:inline hidden">{`${warningCount} ${warningLabel}`}</span>
          <span className="xs:hidden">{warningCount}</span>
        </Badge>
      ) : null}
    </div>
  );
}

function ValidationIssuesList({
  issues,
}: {
  readonly issues: readonly ExtendedValidationIssue[];
}): JSX.Element | null {
  if (issues.length === 0) {
    return null;
  }

  return (
    <div className="max-h-32 overflow-y-auto border-t bg-muted/30 p-2">
      <div className="space-y-1">
        {issues.map((issue) => (
          <ValidationIssueItem
            key={`${issue.path}:${issue.keyword}:${issue.level}:${issue.line ?? ''}:${issue.column ?? ''}:${issue.message}`}
            issue={issue}
          />
        ))}
      </div>
    </div>
  );
}

function ValidationIssueItem({ issue }: { readonly issue: ExtendedValidationIssue }): JSX.Element {
  const { t } = useTranslation('common');

  const iconMap = {
    error: <AlertCircle className="size-4 text-destructive" aria-hidden="true" />,
    warning: <AlertTriangle className="size-4 text-warning" aria-hidden="true" />,
    info: <Info className="size-4 text-muted-foreground" aria-hidden="true" />,
  };

  const bgMap = {
    error: 'border-l-destructive bg-destructive/5',
    warning: 'border-l-warning bg-warning/5',
    info: 'border-l-muted-foreground bg-muted/50',
  };

  return (
    <div className={`flex items-start gap-3 rounded-md border-l-4 p-3 ${bgMap[issue.level]}`}>
      <div className="mt-0.5 shrink-0">{iconMap[issue.level]}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm">{issue.message}</p>
        {issue.line !== null || issue.column !== null ? (
          <p className="mt-1 text-muted-foreground text-xs">
            {`${t('labels.line')} ${issue.line}, ${t('labels.column')} ${issue.column}`}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export { ValidationBadges, ValidationIssuesList };
