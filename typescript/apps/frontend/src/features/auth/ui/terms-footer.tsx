import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

const EXTERNAL_URLS = {
  termsOfService: 'https://www.nohiki.com/terms',
  privacyPolicy: 'https://www.nohiki.com/privacy',
} as const;

function TermsFooter(): JSX.Element {
  const { t } = useTranslation(['auth']);

  return (
    <p className="text-balance border-border/70 border-t pt-3 text-center text-[11px] text-muted-foreground leading-relaxed">
      {t('auth:pages.login.terms')}{' '}
      <a
        href={EXTERNAL_URLS.termsOfService}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium underline decoration-border underline-offset-4 transition-colors hover:text-foreground focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t('auth:pages.login.termsLink')}
      </a>{' '}
      {t('auth:pages.register.and')}{' '}
      <a
        href={EXTERNAL_URLS.privacyPolicy}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium underline decoration-border underline-offset-4 transition-colors hover:text-foreground focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t('auth:pages.login.privacyLink')}
      </a>
      {t('auth:pages.login.period', '.')}
    </p>
  );
}

export { TermsFooter };
