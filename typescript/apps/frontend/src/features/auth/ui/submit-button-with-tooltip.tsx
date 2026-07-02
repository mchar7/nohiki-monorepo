import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/button.tsx';

interface SubmitButtonWithTooltipProps {
  readonly isPending: boolean;
  readonly isValid: boolean;
  readonly isRegister: boolean;
}

function getButtonText(
  isPending: boolean,
  translations: { submitting: string; action: string },
): string {
  if (isPending) {
    return translations.submitting;
  }
  return translations.action;
}

function SubmitButtonWithTooltip({
  isPending,
  isValid,
  isRegister,
}: Readonly<SubmitButtonWithTooltipProps>): JSX.Element {
  const { t } = useTranslation(['auth']);
  const isDisabled = isPending || !isValid;

  const submittingText = isRegister ? t('pages.register.submitting') : t('pages.login.submitting');
  const actionText = isRegister ? t('actions.signUp') : t('actions.signIn');

  const translations = { submitting: submittingText, action: actionText };
  const buttonText = getButtonText(isPending, translations);

  return (
    <Button
      type="submit"
      className="h-10 w-full rounded-lg font-semibold shadow-sm"
      disabled={isDisabled}
    >
      {isPending ? <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" /> : null}
      {buttonText}
    </Button>
  );
}

export { SubmitButtonWithTooltip };
