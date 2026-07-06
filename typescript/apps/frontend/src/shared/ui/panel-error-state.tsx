import { cn } from '@shared/lib/index.ts';
import { AlertCircle } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from './alert.tsx';
import { Button } from './button.tsx';

const NON_ALPHANUMERIC_RE = /[^a-z0-9]/gu;
const BULLET_PREFIX_RE = /^\s*•\s*/u;

interface PanelErrorStateProps {
  title?: string | undefined;
  error: string;
  onRetry?: (() => void) | undefined;
  className?: string | undefined;
}

export function PanelErrorState({
  title,
  error,
  onRetry,
  className,
}: Readonly<PanelErrorStateProps>): JSX.Element {
  const { t } = useTranslation('common');
  const displayTitle = title ?? t('errorBoundary.title');
  // Check if error is essentially the same as title (avoid redundancy)
  const normalizeText = (text: string): string =>
    text.toLowerCase().replaceAll(NON_ALPHANUMERIC_RE, '');
  const isRedundant =
    normalizeText(displayTitle).includes(normalizeText(error)) ||
    normalizeText(error).includes(normalizeText(displayTitle));

  // Parse validation errors to create a more readable format
  const parseValidationError = (errorText: string): string[] => {
    // Handle the actual format: "Please fix the following data validation errors:\n\nSection:\n  • field: message\n  • field: message"
    const lines = errorText.split('\n').filter((line) => line.trim());

    // Find lines that start with bullet points
    const errorLines = lines.filter((line) => line.trim().startsWith('•'));

    if (errorLines.length === 0) {
      return [errorText];
    }

    return errorLines.map((line) => {
      // Remove the bullet point and extra spaces, format the field name
      const cleaned = line.replace(BULLET_PREFIX_RE, '').trim();
      const colonIndex = cleaned.indexOf(':');

      if (colonIndex > 0) {
        const fieldName = cleaned.substring(0, colonIndex).replaceAll('_', ' ');
        const message = cleaned.substring(colonIndex + 1).trim();
        return `${fieldName}: ${message}`;
      }

      return cleaned;
    });
  };

  const errorList = parseValidationError(error);

  return (
    <div className={cn('flex min-h-96 items-center justify-center p-6', className)}>
      <div className="w-full max-w-md space-y-4">
        <Alert variant="destructive">
          <AlertCircle className="size-4" aria-hidden="true" />
          <AlertTitle>{displayTitle}</AlertTitle>
          {/* Only show description if it's not redundant with the title */}
          {!isRedundant && (
            <AlertDescription className="mt-2">
              {errorList.length > 1 ? (
                <div className="space-y-2">
                  <p className="font-medium">{t('errors.fixIssues')}</p>
                  <ul className="ml-4 space-y-1">
                    {errorList.map((errorItem) => (
                      <li key={errorItem} className="list-disc">
                        {errorItem}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p>{errorList[0]}</p>
              )}
            </AlertDescription>
          )}
        </Alert>

        {onRetry ? (
          <div className="flex justify-center">
            <Button onClick={onRetry} variant="outline" size="sm">
              {t('actions.tryAgain')}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
