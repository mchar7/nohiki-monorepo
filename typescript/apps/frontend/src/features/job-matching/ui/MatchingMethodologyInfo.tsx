import { X } from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { Button } from '@/shared/ui/button.tsx';

const DISMISSED_KEY = 'nohiki:matching-methodology-dismissed';

function MatchingMethodologyInfo(): JSX.Element | null {
  const { t } = useTranslation(['jobs']);
  const [dismissed, setDismissed] = useState<boolean>(
    () => localStorage.getItem(DISMISSED_KEY) === 'true',
  );

  if (dismissed) {
    return null;
  }

  const handleDismiss = (): void => {
    localStorage.setItem(DISMISSED_KEY, 'true');
    setDismissed(true);
  };

  return (
    <Alert className="relative pr-12">
      <AlertTitle>{t('match.methodology.title')}</AlertTitle>
      <AlertDescription>{t('match.methodology.description')}</AlertDescription>
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-3 right-3 size-6"
        onClick={handleDismiss}
        aria-label={t('match.methodology.dismiss')}
      >
        <X className="size-4" />
      </Button>
    </Alert>
  );
}

export { MatchingMethodologyInfo };
