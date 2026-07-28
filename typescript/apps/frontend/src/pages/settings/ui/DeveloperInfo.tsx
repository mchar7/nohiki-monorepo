import { Code, Copy, Info, Trash2 } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

/** Duration to show copy-success feedback before resetting (ms) */
const COPY_SUCCESS_RESET_MS: number = 2000;

import { logger } from '@/shared/lib/index.ts';
import { Alert, AlertDescription } from '@/shared/ui/alert.tsx';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';

interface EnvironmentInfo {
  mode: string;
  nodeEnv: string;
  apiBaseUrl: string;
  buildTime?: string | undefined;
  version?: string | undefined;
}

type DebugInfo = Record<string, string | number | boolean>;

function getModeColor(mode: string): string {
  switch (mode) {
    case 'development':
      return 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800';
    case 'production':
      return 'bg-green-100 text-green-800 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800';
    case 'test':
      return 'bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-950 dark:text-yellow-300 dark:border-yellow-800';
    default:
      return 'bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-950 dark:text-gray-300 dark:border-gray-800';
  }
}

function EnvironmentCard({ envInfo }: { readonly envInfo: EnvironmentInfo }): JSX.Element {
  const { t } = useTranslation('settings');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Code className="size-5" />
          {t('developer.environment.title')}
        </CardTitle>
        <CardDescription>{t('developer.environment.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-sm">
                {`${t('developer.environment.mode')}:`}
              </span>
              <Badge variant="outline" className={getModeColor(envInfo.mode)}>
                {envInfo.mode}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-sm">
                {`${t('developer.environment.nodeEnv')}:`}
              </span>
              <Badge variant="outline">{envInfo.nodeEnv}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-sm">
                {`${t('developer.environment.apiBaseUrl')}:`}
              </span>
              <code className="rounded bg-muted px-2 py-1 text-xs">{envInfo.apiBaseUrl}</code>
            </div>
          </div>
          <div className="space-y-3">
            {envInfo.version ? (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.environment.version')}:`}
                </span>
                <Badge variant="outline">{envInfo.version}</Badge>
              </div>
            ) : null}
            {envInfo.buildTime ? (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.environment.buildTime')}:`}
                </span>
                <span className="text-muted-foreground text-xs">
                  {Intl.DateTimeFormat(undefined, {
                    dateStyle: 'short',
                    timeStyle: 'medium',
                  }).format(new Date(envInfo.buildTime))}
                </span>
              </div>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function BrowserInfoCard({ debugInfo }: { readonly debugInfo: DebugInfo }): JSX.Element {
  const { t } = useTranslation('settings');

  const onLineBadgeVariant: 'default' | 'destructive' = debugInfo.onLine
    ? 'default'
    : 'destructive';
  const localStorageBadgeVariant: 'default' | 'destructive' =
    debugInfo.localStorage === 'available' ? 'default' : 'destructive';

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Info className="size-5" />
          {t('developer.browser.title')}
        </CardTitle>
        <CardDescription>{t('developer.browser.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.platform')}:`}
                </span>
                <span className="text-xs">{debugInfo.platform}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.language')}:`}
                </span>
                <span className="text-xs">{debugInfo.language}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.timezone')}:`}
                </span>
                <span className="text-xs">{debugInfo.timezone}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.online')}:`}
                </span>
                <Badge variant={onLineBadgeVariant}>{debugInfo.onLine ? 'Yes' : 'No'}</Badge>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.windowSize')}:`}
                </span>
                <span className="text-xs">{debugInfo.windowSize}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.screenSize')}:`}
                </span>
                <span className="text-xs">{debugInfo.screen}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.pixelRatio')}:`}
                </span>
                <span className="text-xs">{debugInfo.pixelRatio}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-sm">
                  {`${t('developer.browser.localStorage')}:`}
                </span>
                <Badge variant={localStorageBadgeVariant}>{debugInfo.localStorage}</Badge>
              </div>
            </div>
          </div>

          {/* User Agent */}
          <div className="mt-4">
            <span className="mb-2 block text-muted-foreground text-sm">
              {`${t('developer.browser.userAgent')}:`}
            </span>
            <code className="block break-all rounded bg-muted p-2 text-xs">
              {debugInfo.userAgent}
            </code>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface DebugActionsCardProps {
  readonly copySuccess: boolean;
  readonly cacheClearError: string | null;
  readonly onCopyDebugInfo: () => void;
  readonly onClearCache: () => void;
}

function DebugActionsCard({
  cacheClearError,
  copySuccess,
  onCopyDebugInfo,
  onClearCache,
}: DebugActionsCardProps): JSX.Element {
  const { t } = useTranslation('settings');

  const copyButtonLabel = copySuccess
    ? t('developer.actions.copied')
    : t('developer.actions.copyDebugInfo');

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('developer.actions.title')}</CardTitle>
        <CardDescription>{t('developer.actions.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          <div className="flex gap-2">
            <Button onClick={onCopyDebugInfo} variant="outline" size="sm">
              <Copy className="mr-2 size-4" />
              {copyButtonLabel}
            </Button>
            <Button onClick={onClearCache} variant="destructive" size="sm">
              <Trash2 className="mr-2 size-4" />
              {t('developer.actions.clearCache')}
            </Button>
          </div>

          <div className="text-muted-foreground text-sm">
            <p>
              <strong>{`${t('developer.actions.clearCache')}:`}</strong>{' '}
              {t('developer.actions.clearCacheHelp')}
            </p>
          </div>
        </div>

        {copySuccess ? (
          <Alert className="mt-3 border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950">
            <AlertDescription className="text-sm">
              {t('developer.actions.copiedAlert')}
            </AlertDescription>
          </Alert>
        ) : null}
        {cacheClearError ? (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription className="text-sm">{cacheClearError}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

const ENV_INFO: EnvironmentInfo = {
  mode: import.meta.env.MODE || 'development',
  nodeEnv: import.meta.env.MODE || 'unknown',
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  buildTime: import.meta.env.VITE_BUILD_TIME,
  version: import.meta.env.VITE_APP_VERSION || '0.1.0',
};

/** Manages debug info collection, clipboard copy, and cache clearing. */
function useDeveloperActions(): {
  cacheClearError: string | null;
  copySuccess: boolean;
  debugInfo: DebugInfo;
  handleCopyDebugInfo: () => Promise<void>;
  handleClearCache: () => Promise<void>;
} {
  const [copySuccess, setCopySuccess] = useState(false);
  const [cacheClearError, setCacheClearError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<DebugInfo>({});

  useEffect(() => {
    setDebugInfo({
      userAgent: navigator.userAgent,
      language: navigator.language,
      cookieEnabled: navigator.cookieEnabled,
      onLine: navigator.onLine,
      windowSize: `${globalThis.innerWidth}x${globalThis.innerHeight}`,
      screen: `${screen.width}x${screen.height}`,
      pixelRatio: globalThis.devicePixelRatio,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      localStorage: 'localStorage' in globalThis ? 'available' : 'unavailable',
      indexedDB: 'indexedDB' in globalThis ? 'available' : 'unavailable',
    });
  }, []);

  const handleCopyDebugInfo = async (): Promise<void> => {
    const debugText = `
=== Nohiki - Debug Information ===
Generated: ${new Date().toISOString()}

Environment:
${Object.entries(ENV_INFO)
  .map(([key, value]) => `  ${key}: ${value || 'undefined'}`)
  .join('\n')}

Browser/System:
${Object.entries(debugInfo)
  .map(([key, value]) => `  ${key}: ${value}`)
  .join('\n')}

Current URL: ${globalThis.location.href}
Referrer: ${document.referrer || 'none'}
    `.trim();

    try {
      await navigator.clipboard.writeText(debugText);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), COPY_SUCCESS_RESET_MS);
    } catch {
      // Clipboard API unavailable - silently fail
    }
  };

  const handleClearCache = async (): Promise<void> => {
    setCacheClearError(null);
    try {
      localStorage.clear();
      sessionStorage.clear();

      if ('indexedDB' in globalThis && indexedDB.databases) {
        const databases = await indexedDB.databases();
        await Promise.all(
          databases.flatMap((database) => {
            if (!database.name) return [];
            return [
              new Promise<void>((resolve, reject) => {
                const request = indexedDB.deleteDatabase(database.name as string);
                request.onsuccess = () => resolve();
                request.onerror = () =>
                  reject(request.error ?? new Error('IndexedDB deletion failed'));
                request.onblocked = () =>
                  reject(new Error(`IndexedDB deletion blocked: ${database.name}`));
              }),
            ];
          }),
        );
      }

      globalThis.location.reload();
    } catch (error) {
      logger.error('Failed to clear browser cache', error);
      setCacheClearError(error instanceof Error ? error.message : 'Failed to clear browser cache');
    }
  };

  return { cacheClearError, copySuccess, debugInfo, handleCopyDebugInfo, handleClearCache };
}

export function DeveloperInfo(): JSX.Element {
  const { cacheClearError, copySuccess, debugInfo, handleCopyDebugInfo, handleClearCache } =
    useDeveloperActions();

  return (
    <div className="space-y-4">
      <EnvironmentCard envInfo={ENV_INFO} />
      <BrowserInfoCard debugInfo={debugInfo} />
      <DebugActionsCard
        cacheClearError={cacheClearError}
        copySuccess={copySuccess}
        onCopyDebugInfo={handleCopyDebugInfo}
        onClearCache={handleClearCache}
      />
    </div>
  );
}
