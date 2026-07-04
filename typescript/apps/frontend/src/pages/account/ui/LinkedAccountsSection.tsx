import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { OAuthProvider } from '@/shared/api';
import { oauthApi } from '@/shared/api/index.ts';
import { TOAST_ERROR } from '@/shared/lib';
import { extractErrorReason } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { GitHubIcon, GoogleIcon } from '@/shared/ui/icons.tsx';
import { useOAuthIdentities, useOAuthProviders, useUnlinkOAuth } from '../api/index.ts';

interface Identity {
  provider: string;
  provider_email?: string | null;
  provider_username?: string | null;
  linked_at: string;
}

interface Provider {
  id: OAuthProvider;
  name: string;
  enabled: boolean;
}

interface ProviderRowProps {
  provider: Provider;
  identity: Identity | undefined;
  isUnlinkPending: boolean;
  isUnlinkingThisProvider: boolean;
  canUnlink: boolean;
  dateFormatter: Intl.DateTimeFormat;
  onUnlink: (provider: OAuthProvider) => void;
  onLink: (provider: OAuthProvider) => void;
}

function ProviderRow({
  provider,
  identity,
  isUnlinkPending,
  isUnlinkingThisProvider,
  canUnlink,
  dateFormatter,
  onUnlink,
  onLink,
}: ProviderRowProps): JSX.Element {
  const { t } = useTranslation('account');
  const Icon = provider.id === 'github' ? GitHubIcon : GoogleIcon;
  const linkedDetail = identity
    ? `${identity.provider_email ?? identity.provider_username} • ${t('sections.linkedAccounts.linkedOn', { date: dateFormatter.format(new Date(identity.linked_at)) })}`
    : null;

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
      <div className="flex items-center gap-4">
        <div className="flex size-10 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5" />
        </div>
        <div>
          <p className="font-medium text-sm">{provider.name}</p>
          <p className="text-muted-foreground text-xs">
            {linkedDetail ?? t('sections.linkedAccounts.notLinked')}
          </p>
        </div>
      </div>
      {identity ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onUnlink(provider.id)}
          disabled={isUnlinkPending || !canUnlink}
        >
          {isUnlinkingThisProvider ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
          {t('sections.linkedAccounts.unlink')}
        </Button>
      ) : (
        <Button variant="outline" size="sm" onClick={() => onLink(provider.id)}>
          {t('sections.linkedAccounts.link')}
        </Button>
      )}
    </div>
  );
}

interface LinkedAccountsCardProps {
  providers: Provider[];
  identitiesByProvider: Map<string, Identity>;
  canUnlink: boolean;
  dateFormatter: Intl.DateTimeFormat;
  isUnlinkPending: boolean;
  unlinkingProvider: OAuthProvider | undefined;
  onUnlink: (provider: OAuthProvider) => void;
  onLink: (provider: OAuthProvider) => void;
}

function LinkedAccountsCard({
  providers,
  identitiesByProvider,
  canUnlink,
  dateFormatter,
  isUnlinkPending,
  unlinkingProvider,
  onUnlink,
  onLink,
}: LinkedAccountsCardProps): JSX.Element {
  const { t } = useTranslation('account');

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('account:sections.linkedAccounts.title')}</CardTitle>
        <CardDescription>{t('account:sections.linkedAccounts.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-4">
          {providers
            .filter((provider) => provider.enabled)
            .map((provider) => (
              <ProviderRow
                key={provider.id}
                provider={provider}
                identity={identitiesByProvider.get(provider.id)}
                isUnlinkPending={isUnlinkPending}
                isUnlinkingThisProvider={unlinkingProvider === provider.id}
                canUnlink={canUnlink}
                dateFormatter={dateFormatter}
                onUnlink={onUnlink}
                onLink={onLink}
              />
            ))}
        </div>
        {canUnlink ? null : (
          <p className="text-muted-foreground text-xs">
            {t('account:sections.linkedAccounts.unlinkDisabledWarning')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function LinkedAccountsSection(): JSX.Element {
  const { t, i18n } = useTranslation(['account', 'common']);
  const { data: identitiesData, isLoading: identitiesLoading } = useOAuthIdentities();
  const { data: providersData, isLoading: providersLoading } = useOAuthProviders();
  const unlinkMutation = useUnlinkOAuth();

  if (identitiesLoading || providersLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('account:sections.linkedAccounts.title')}</CardTitle>
          <CardDescription>{t('account:sections.linkedAccounts.description')}</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center py-8">
          <Loader2 className="size-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const identities = identitiesData?.identities ?? [];
  const hasPassword = identitiesData?.has_password ?? false;
  const providers = providersData?.providers ?? [];
  const identitiesByProvider = new Map(
    identities.map((identity) => [identity.provider, identity] as const),
  );
  const dateFormatter = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' });
  const canUnlink = identities.length > 1 || hasPassword;

  const handleUnlink = async (provider: OAuthProvider): Promise<void> => {
    try {
      await unlinkMutation.mutateAsync({ params: { path: { provider } } });
      toast.success(t('account:feedback.unlinkSuccess'));
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t(TOAST_ERROR.PROFILE_UPDATE_FAILED, { reason })
          : t('account:feedback.updateErrorFallback'),
      );
    }
  };

  const handleLink = (provider: OAuthProvider): void => {
    globalThis.location.href = oauthApi.getAuthorizeUrl(provider, '/account');
  };

  return (
    <LinkedAccountsCard
      providers={providers}
      identitiesByProvider={identitiesByProvider}
      canUnlink={canUnlink}
      dateFormatter={dateFormatter}
      isUnlinkPending={unlinkMutation.isPending}
      unlinkingProvider={unlinkMutation.variables?.params.path.provider}
      onUnlink={handleUnlink}
      onLink={handleLink}
    />
  );
}

export { LinkedAccountsSection };
