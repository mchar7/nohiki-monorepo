import { Eye, Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';

interface FloatingPreviewButtonProps {
  readonly onClick: () => void;
  readonly className?: string;
  readonly isLoading?: boolean;
}

export function FloatingPreviewButton({
  onClick,
  className,
  isLoading = false,
}: FloatingPreviewButtonProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');

  return (
    <Button
      onClick={onClick}
      disabled={isLoading}
      size="lg"
      className={cn(
        'fixed right-6 bottom-6 z-50 h-14 w-14 rounded-full shadow-lg',
        'transition-shadow duration-200 hover:shadow-xl',
        className,
      )}
    >
      {isLoading ? <Loader2 className="size-6 animate-spin" /> : <Eye className="size-6" />}
      <span className="sr-only">
        {isLoading ? t('floatingButton.generating') : t('floatingButton.preview')}
      </span>
    </Button>
  );
}
