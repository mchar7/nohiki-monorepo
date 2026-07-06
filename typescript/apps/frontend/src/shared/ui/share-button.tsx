import { Check, Share2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useCopyToClipboard } from '@/shared/lib/index.ts';
import { Button } from './button.tsx';
import type { ShareButtonProps } from './share-button.types.ts';

/** Icon button that copies a URL to the clipboard and shows a toast confirmation. */
function ShareButton({ url }: ShareButtonProps): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const [copy, isCopied] = useCopyToClipboard();

  const handleClick = async (): Promise<void> => {
    const target = url ?? globalThis.location.href;
    await copy(target);
    toast.success(t('actions.linkCopied'));
  };

  return (
    <Button variant="ghost" size="icon" onClick={handleClick} aria-label={t('actions.share')}>
      {isCopied ? (
        <Check className="size-4" aria-hidden="true" />
      ) : (
        <Share2 className="size-4" aria-hidden="true" />
      )}
    </Button>
  );
}

export { ShareButton };
