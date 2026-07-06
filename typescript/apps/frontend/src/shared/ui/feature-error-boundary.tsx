import { AlertTriangle, Check, ClipboardCopy, RefreshCw } from 'lucide-react';
import type { JSX } from 'react';
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { i18n } from '@/shared/lib/i18n.ts';
import { useCopyToClipboard } from '@/shared/lib/index.ts';
import { Button } from './button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './card.tsx';

type FeatureKey =
  | 'accountSettings'
  | 'attachments'
  | 'auth'
  | 'dashboard'
  | 'documentEditor'
  | 'documents'
  | 'jobDetail'
  | 'jobListings'
  | 'jobMatches'
  | 'licenses'
  | 'matchDetail'
  | 'omakase'
  | 'omakaseEditor'
  | 'omakaseTemplates'
  | 'profileCreate'
  | 'profileDetail'
  | 'profileList'
  | 'settings';

interface FeatureErrorBoundaryProps {
  /** The i18n key for the feature name - must match common:features.{key} */
  readonly featureKey: FeatureKey;
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
  readonly onError?: (error: Error, errorInfo: ErrorInfo) => void;
  readonly showDetails?: boolean;
}

interface FeatureErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

interface ErrorStackDisplayProps {
  readonly message: string;
  readonly componentStack: string | undefined;
}

/** Renders the error stack with a copy-to-clipboard button. Uses hooks internally. */
function ErrorStackDisplay({ message, componentStack }: ErrorStackDisplayProps): JSX.Element {
  const { t } = useTranslation('common');
  const [copy, isCopied] = useCopyToClipboard();

  const fullText = componentStack ? `${message}\n\n${componentStack}` : message;
  const CopyIcon = isCopied ? Check : ClipboardCopy;

  return (
    <div className="rounded-md bg-muted p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-destructive text-sm">{message}</p>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 gap-1.5 px-2 text-xs"
          onClick={() => copy(fullText)}
          aria-label={t('actions.copyErrorStack')}
        >
          <CopyIcon className="size-3.5" aria-hidden="true" />
          {isCopied ? t('actions.copied') : t('actions.copyErrorStack')}
        </Button>
      </div>
      {componentStack ? (
        <pre className="mt-2 max-h-32 overflow-auto text-muted-foreground text-xs">
          {componentStack}
        </pre>
      ) : null}
    </div>
  );
}

/**
 * Feature-level error boundary that provides graceful error handling
 * for specific features without crashing the entire application.
 *
 * Usage:
 * ```tsx
 * <FeatureErrorBoundary featureKey="documentEditor">
 *   <Editor />
 * </FeatureErrorBoundary>
 * ```
 *
 * The featureKey maps to translations in common:features.{key}
 */
export class FeatureErrorBoundary extends Component<
  FeatureErrorBoundaryProps,
  FeatureErrorBoundaryState
> {
  constructor(props: FeatureErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<FeatureErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  handleReload = (): void => {
    globalThis.location.reload();
  };

  render(): ReactNode {
    const { hasError, error, errorInfo } = this.state;
    const { featureKey, children, fallback, showDetails } = this.props;

    if (hasError) {
      if (fallback) {
        return fallback;
      }

      const isDev = import.meta.env.DEV;
      const shouldShowDetails = showDetails ?? isDev;
      const featureName = i18n.t(`features.${featureKey}`);

      return (
        <div className="flex h-full items-center justify-center p-6">
          <Card className="w-full max-w-lg">
            <CardHeader className="text-center">
              <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-destructive/10">
                <AlertTriangle className="size-6 text-destructive" />
              </div>
              <CardTitle>{i18n.t('errors.generic')}</CardTitle>
              <CardDescription>
                {i18n.t('errorBoundary.featureError', { feature: featureName })}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {shouldShowDetails && error ? (
                <ErrorStackDisplay
                  message={error.message}
                  componentStack={errorInfo?.componentStack?.toString()}
                />
              ) : null}
              <div className="flex justify-center gap-3">
                <Button onClick={this.handleRetry} className="gap-2">
                  <RefreshCw className="size-4" />
                  {i18n.t('actions.tryAgain')}
                </Button>
                <Button variant="outline" onClick={this.handleReload}>
                  {i18n.t('actions.refresh')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      );
    }

    return children;
  }
}
