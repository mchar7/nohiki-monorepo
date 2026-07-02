import { cn } from '@shared/lib/index.ts';
import type React from 'react';
import type { JSX } from 'react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useResizeObserver } from '@/shared/lib/index.ts';

interface PreviewRendererProps {
  htmlUrl?: string | null;
  imageUrl?: string | null;
  isInDialog?: boolean;
  isFullscreen?: boolean;
  className?: string;
}

/** Gap in pixels around the iframe for scaling calculations */
const IFRAME_GAP = 16;

function applyIframeScale(iframe: HTMLIFrameElement, container: HTMLElement): void {
  try {
    const doc = iframe.contentDocument;
    if (!doc?.documentElement) {
      return;
    }

    const docWidth = doc.documentElement.scrollWidth;
    const docHeight = doc.documentElement.scrollHeight;
    if (!(docWidth && docHeight)) {
      return;
    }

    const availableWidth = container.clientWidth - IFRAME_GAP * 2;
    const availableHeight = container.clientHeight - IFRAME_GAP * 2;
    const scale = Math.min(availableWidth / docWidth, availableHeight / docHeight);

    iframe.style.transform = `scale(${scale})`;
    iframe.style.transformOrigin = 'top left';
    iframe.style.width = `${docWidth}px`;
    iframe.style.height = `${docHeight}px`;
    iframe.style.position = 'absolute';
  } catch {
    // Sandboxed previews have an opaque origin and intentionally deny parent DOM access.
  }
}

function useIframeScaling(
  iframeRef: React.RefObject<HTMLIFrameElement | null>,
  containerRef: React.RefObject<HTMLDivElement | null>,
  containerSize: { width: number; height: number } | undefined,
): { handleIframeLoad: () => void } {
  useEffect(() => {
    if (containerSize) {
      const iframe = iframeRef.current;
      const container = containerRef.current;
      if (iframe && container) {
        applyIframeScale(iframe, container);
      }
    }
  }, [containerSize, iframeRef, containerRef]);

  const handleIframeLoad = (): void => {
    const iframe = iframeRef.current;
    if (!iframe) {
      return;
    }

    const scaleToFit = (): void => {
      const container = containerRef.current;
      if (iframe && container) {
        applyIframeScale(iframe, container);
      }
    };

    const performScale = (): void => {
      requestAnimationFrame((): void => {
        requestAnimationFrame(scaleToFit);
      });
    };

    try {
      const doc = iframe.contentDocument;
      if (doc?.fonts) {
        doc.fonts.ready.then(performScale);
        return;
      }
    } catch {
      // Cross-origin iframe - contentDocument not accessible
    }

    performScale();
  };

  return { handleIframeLoad };
}

function PreviewRenderer({
  htmlUrl,
  imageUrl,
  isInDialog = false,
  isFullscreen = false,
  className,
}: PreviewRendererProps): JSX.Element | null {
  const { t } = useTranslation('omakase.preview');
  const [containerRef, containerSize] = useResizeObserver<HTMLDivElement>();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { handleIframeLoad } = useIframeScaling(iframeRef, containerRef, containerSize);

  const containerClasses = cn(
    'h-full w-full overflow-hidden relative',
    isInDialog ? 'bg-white' : '',
    isFullscreen && !isInDialog && 'fixed inset-0 z-50 bg-white',
    className,
  );

  if (htmlUrl) {
    return (
      <div ref={containerRef} className={containerClasses}>
        {/* biome-ignore lint/a11y/noNoninteractiveElementInteractions: iframe onLoad is a standard page lifecycle event, not a user interaction handler */}
        <iframe
          ref={iframeRef}
          src={htmlUrl}
          className="block size-full border-0"
          title={t('a11y.iframeTitle')}
          sandbox={htmlUrl.startsWith('blob:') ? 'allow-same-origin' : ''}
          onLoad={handleIframeLoad}
        />
      </div>
    );
  }

  if (imageUrl) {
    return (
      <div ref={containerRef} className={containerClasses}>
        <div className="flex h-full w-full items-center justify-center p-4">
          <img
            src={imageUrl}
            alt={t('a11y.imageAlt')}
            className="mx-auto max-h-full max-w-full rounded object-contain shadow-sm"
          />
        </div>
      </div>
    );
  }

  return null;
}

export { PreviewRenderer };
