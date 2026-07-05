import { useDocumentSSE } from '@features/document-generation';
import { Link } from '@tanstack/react-router';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { type JSX, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ROUTE_PATHS } from '@/shared/config';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { Progress } from '@/shared/ui/progress.tsx';

const TIMER_INTERVAL_MS = 1000;
const SECONDS_PER_MINUTE = 60;

interface GenerationProgressProps {
  readonly requestId: string;
  readonly onRetry: () => void;
}

function useElapsedTime(isRunning: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    startRef.current = Date.now();
    setElapsed(0);

    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / TIMER_INTERVAL_MS));
    }, TIMER_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [isRunning]);

  return elapsed;
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / SECONDS_PER_MINUTE);
  const seconds = totalSeconds % SECONDS_PER_MINUTE;
  const paddedSeconds = String(seconds).padStart(2, '0');
  if (minutes > 0) {
    return `${String(minutes)}:${paddedSeconds}`;
  }
  return `0:${paddedSeconds}`;
}

function GenerationProgress({ requestId, onRetry }: GenerationProgressProps): JSX.Element {
  const { t } = useTranslation('documents');
  const { status, downloadUrl, error, progress } = useDocumentSSE(requestId);

  const isInProgress = status === 'idle' || status === 'connecting' || status === 'connected';
  const elapsed = useElapsedTime(isInProgress);

  if (status === 'completed') {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-6 py-12">
          <div className="flex size-16 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-950">
            <CheckCircle2
              className="size-8 text-emerald-600 dark:text-emerald-400"
              aria-hidden="true"
            />
          </div>
          <div className="text-center">
            <h2 className="font-semibold text-lg">{t('progress.completedTitle')}</h2>
            <p className="mt-1 text-muted-foreground text-sm">
              {t('progress.completedDescription')}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {downloadUrl !== null && (
              <Button asChild={true}>
                <a href={downloadUrl} download={true} aria-label={t('progress.a11y.downloadPdf')}>
                  <Download className="mr-2 size-4" aria-hidden="true" />
                  {t('progress.downloadPdf')}
                </a>
              </Button>
            )}
            <Button variant="outline" asChild={true}>
              <Link to={ROUTE_PATHS.DOCUMENTS.LIST} aria-label={t('progress.a11y.viewDocuments')}>
                <ExternalLink className="mr-2 size-4" aria-hidden="true" />
                {t('progress.viewDocuments')}
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === 'failed') {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-6 py-12">
          <div className="flex size-16 items-center justify-center rounded-full bg-destructive/10">
            <AlertCircle className="size-8 text-destructive" aria-hidden="true" />
          </div>
          <div className="text-center">
            <h2 className="font-semibold text-lg">{t('progress.failedTitle')}</h2>
            <p className="mt-1 text-muted-foreground text-sm">
              {error ?? t('progress.failedFallback')}
            </p>
          </div>
          <Button onClick={onRetry} variant="outline" aria-label={t('progress.a11y.retry')}>
            <RefreshCw className="mr-2 size-4" aria-hidden="true" />
            {t('progress.retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-6 py-12" aria-live="polite">
        <div className="flex size-16 items-center justify-center rounded-full bg-primary/10">
          <Loader2 className="size-8 animate-spin text-primary" aria-hidden="true" />
        </div>
        <div className="text-center">
          <h2 className="font-semibold text-lg">{t('progress.title')}</h2>
          <p className="mt-1 text-muted-foreground text-sm">{t('progress.description')}</p>
        </div>
        <div className="w-full max-w-xs space-y-2">
          <Progress value={progress} aria-label={t('progress.a11y.progressBar')} />
          <div className="flex justify-between text-muted-foreground text-xs">
            <span>{t('progress.percentComplete', { progress })}</span>
            <time>{formatElapsed(elapsed)}</time>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export { GenerationProgress };
