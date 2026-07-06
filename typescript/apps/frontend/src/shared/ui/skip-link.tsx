import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

/** Keyboard-accessible skip link that jumps to the main content area. Visually hidden until focused. */
function SkipLink(): JSX.Element {
  const { t } = useTranslation(['common']);

  return (
    <a
      href="#main-content"
      data-testid="skip-link"
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded focus:bg-background focus:px-4 focus:py-2 focus:font-medium focus:text-foreground focus:text-sm focus:shadow-lg focus:ring-2 focus:ring-ring"
    >
      {t('a11y.skipToContent')}
    </a>
  );
}

export { SkipLink };
