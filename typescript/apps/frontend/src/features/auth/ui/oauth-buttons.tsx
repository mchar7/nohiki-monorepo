import type { JSX } from 'react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { oauthApi } from '@/shared/api/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { GitHubIcon, GoogleIcon } from '@/shared/ui/icons.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/shared/ui/tooltip.tsx';
import { OAuthProvider } from '../model/index.ts';

interface ProviderState {
  google: boolean;
  github: boolean;
}

interface OAuthButtonsProps {
  readonly returnUrl?: string | undefined;
}

/** Fetches which OAuth providers are enabled and tracks loading state. */
function useEnabledProviders(): { enabled: ProviderState; isLoading: boolean } {
  const [isLoading, setIsLoading] = useState(true);
  const [enabled, setEnabled] = useState<ProviderState>({ google: false, github: false });

  useEffect(() => {
    let mounted = true;
    oauthApi
      .getProviders()
      .then((res) => {
        if (!mounted) {
          return;
        }
        const providers = res.providers ?? [];
        setEnabled({
          google: providers.some((p) => p.id === OAuthProvider.GOOGLE && p.enabled),
          github: providers.some((p) => p.id === OAuthProvider.GITHUB && p.enabled),
        });
      })
      .catch((): void => {
        if (mounted) {
          setEnabled({ google: false, github: false });
        }
      })
      .finally((): void => {
        if (mounted) {
          setIsLoading(false);
        }
      });
    return (): void => {
      mounted = false;
    };
  }, []);

  return { enabled, isLoading };
}

function OAuthButtons({ returnUrl }: OAuthButtonsProps): JSX.Element {
  const { t } = useTranslation('auth');
  const { enabled, isLoading } = useEnabledProviders();

  if (isLoading) {
    return (
      <fieldset
        className="grid min-w-0 grid-cols-2 gap-2 border-0 p-0"
        aria-label={t('social.providers')}
      >
        <Skeleton className="h-10 w-full rounded-lg" />
        <Skeleton className="h-10 w-full rounded-lg" />
      </fieldset>
    );
  }

  return (
    <TooltipProvider delayDuration={700} skipDelayDuration={300}>
      <fieldset
        className="grid min-w-0 grid-cols-2 gap-2 border-0 p-0"
        aria-label={t('social.providers')}
      >
        <OAuthProviderControl
          provider="Google"
          testId="oauth-google"
          enabled={enabled.google}
          onClick={() => {
            globalThis.location.href = oauthApi.getAuthorizeUrl(OAuthProvider.GOOGLE, returnUrl);
          }}
          icon={<GoogleIcon className="size-4 shrink-0" aria-hidden="true" />}
        />
        <OAuthProviderControl
          provider="GitHub"
          testId="oauth-github"
          enabled={enabled.github}
          onClick={() => {
            globalThis.location.href = oauthApi.getAuthorizeUrl(OAuthProvider.GITHUB, returnUrl);
          }}
          icon={<GitHubIcon className="size-4 shrink-0" aria-hidden="true" />}
        />
      </fieldset>
    </TooltipProvider>
  );
}

interface OAuthProviderControlProps {
  provider: string;
  testId: string;
  enabled: boolean;
  onClick: () => void;
  icon: React.ReactNode;
}

function OAuthProviderControl({
  provider,
  testId,
  enabled,
  onClick,
  icon,
}: Readonly<OAuthProviderControlProps>): JSX.Element {
  const { t } = useTranslation('auth');

  const buttonLabel = t('oauth.continueWith', { provider });
  const button = (
    <Button
      type="button"
      variant="outline"
      className="h-10 w-full gap-1.5 rounded-lg bg-background px-2 font-medium text-xs shadow-xs disabled:cursor-not-allowed"
      disabled={!enabled}
      onClick={onClick}
      aria-label={buttonLabel}
      data-testid={testId}
    >
      {icon}
      <span className="truncate">{buttonLabel}</span>
    </Button>
  );

  if (enabled) {
    return button;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild={true}>
        <span className="block cursor-not-allowed">{button}</span>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        <p>{t('oauth.providerUnavailable', { provider })}</p>
      </TooltipContent>
    </Tooltip>
  );
}

export { OAuthButtons };
