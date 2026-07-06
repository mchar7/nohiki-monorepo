import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';

interface OptionalIndicatorProps {
  readonly className?: string;
}

function OptionalIndicator({ className }: OptionalIndicatorProps): JSX.Element {
  const { t } = useTranslation('common');
  return (
    <span className={cn('font-normal text-muted-foreground text-xs', className)}>
      {t('form.optionalLabel')}
    </span>
  );
}

export { OptionalIndicator };
