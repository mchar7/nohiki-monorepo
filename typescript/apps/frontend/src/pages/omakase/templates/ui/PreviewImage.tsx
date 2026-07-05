import { AlertCircle, Loader2, RefreshCw } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription } from '@/shared/ui/alert.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { calculateDisplaySize } from '../lib/preview-calculations.ts';
import type { PreviewState } from '../model/index.ts';

interface PreviewImageProps {
  readonly previewState: PreviewState;
  readonly onContainerSizeChange: (size: { width: number; height: number }) => void;
  readonly onRegenerateImage?: (() => void) | undefined;
  readonly className?: string | undefined;
}

function GeneratingState(): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  return (
    <div className="flex h-full min-h-50 flex-col items-center justify-center text-muted-foreground">
      <Loader2 className="mb-2 size-8 animate-spin" />
      <p className="text-sm">{t('states.generating')}</p>
    </div>
  );
}

/** Convert technical errors to user-friendly messages */
function getUserFriendlyError(error: string, t: (key: string) => string): string {
  if (error.includes('NetworkError') || error.includes('fetch')) {
    return t('errors.networkError');
  }
  if (error.includes('timeout') || error.includes('Timeout')) {
    return t('errors.timeout');
  }
  if (error.includes('500') || error.includes('Internal Server')) {
    return t('errors.serverError');
  }
  return error;
}

function ErrorState({
  error,
  onRegenerate,
}: {
  readonly error: string;
  readonly onRegenerate?: (() => void) | undefined;
}): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  return (
    <div className="flex h-full min-h-50 flex-col items-center justify-center p-4">
      <div className="w-full max-w-md space-y-4">
        <Alert>
          <AlertCircle className="size-4" />
          <AlertDescription>{getUserFriendlyError(error, t)}</AlertDescription>
        </Alert>
        {onRegenerate ? (
          <div className="flex justify-center">
            <Button variant="outline" size="sm" onClick={onRegenerate}>
              <RefreshCw className="mr-2 size-4" />
              {t('actions.tryAgain')}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function EmptyState({
  onRegenerate,
}: {
  readonly onRegenerate?: (() => void) | undefined;
}): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  return (
    <div className="flex h-full min-h-50 flex-col items-center justify-center text-muted-foreground">
      <div className="text-center">
        <p className="mb-3 text-sm">{t('states.noPreview')}</p>
        {onRegenerate ? (
          <Button variant="outline" size="sm" onClick={onRegenerate}>
            <RefreshCw className="mr-2 size-4" />
            {t('actions.generate')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ImageDisplay({
  imageUrl,
  displaySize,
}: {
  readonly imageUrl: string;
  readonly displaySize: { width: number; height: number };
}): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  return (
    <div
      className="flex h-full w-full items-center justify-center overflow-auto p-4"
      style={{ minWidth: displaySize.width, minHeight: displaySize.height }}
    >
      <img
        src={imageUrl}
        alt={t('title')}
        width={displaySize.width}
        height={displaySize.height}
        className="border border-border shadow-lg"
        style={{
          width: displaySize.width,
          height: displaySize.height,
          maxWidth: 'none',
          maxHeight: 'none',
        }}
        draggable={false}
      />
    </div>
  );
}

export function PreviewImage({
  previewState,
  onContainerSizeChange,
  onRegenerateImage,
  className = '',
}: PreviewImageProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    resizeObserverRef.current = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        onContainerSizeChange({ width, height });
      }
    });

    resizeObserverRef.current.observe(containerRef.current);

    return (): void => {
      resizeObserverRef.current?.disconnect();
    };
  }, [onContainerSizeChange]);

  const displaySize = previewState.imageNaturalSize
    ? calculateDisplaySize(previewState.imageNaturalSize, previewState.scale.percentage)
    : null;

  const renderContent = (): JSX.Element => {
    if (previewState.isGenerating) {
      return <GeneratingState />;
    }
    if (previewState.generationError) {
      return <ErrorState error={previewState.generationError} onRegenerate={onRegenerateImage} />;
    }
    if (!(previewState.imageUrl && displaySize)) {
      return <EmptyState onRegenerate={onRegenerateImage} />;
    }
    return <ImageDisplay imageUrl={previewState.imageUrl} displaySize={displaySize} />;
  };

  return (
    <div
      ref={containerRef}
      className={`relative h-full w-full rounded-lg border bg-muted/30 ${className}`}
    >
      {renderContent()}
    </div>
  );
}
