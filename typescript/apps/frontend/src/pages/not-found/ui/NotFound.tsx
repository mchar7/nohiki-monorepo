import { Link } from '@tanstack/react-router';
import { Home, Search } from 'lucide-react';
import { type JSX, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardHeader } from '@/shared/ui/card.tsx';

export function NotFound(): JSX.Element {
  const { t } = useTranslation();
  const headingId = useId();

  useDocumentTitle(t('pages.notFound.heading'));

  return (
    <main
      aria-labelledby={headingId}
      className="flex min-h-screen items-center justify-center bg-background p-4"
    >
      <Card className="w-full max-w-md text-center">
        <CardHeader className="pb-2">
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-full bg-muted">
            <Search className="size-8 text-muted-foreground" aria-hidden="true" />
          </div>
          <p aria-hidden="true" className="font-bold text-5xl text-muted-foreground">
            {t('pages.notFound.title')}
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h1 id={headingId} className="font-semibold text-foreground text-xl">
              {t('pages.notFound.heading')}
            </h1>
            <p className="text-muted-foreground text-sm">{t('pages.notFound.description')}</p>
          </div>
          <Button asChild={true}>
            <Link to="/">
              <Home className="mr-2 size-4" aria-hidden="true" />
              {t('pages.notFound.goHome')}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
