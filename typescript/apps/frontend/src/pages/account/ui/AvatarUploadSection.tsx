import { ImagePlus } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { UserResponse } from '@/shared/api';
import { Avatar, AvatarFallback } from '@/shared/ui/avatar.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';

interface AvatarUploadSectionProps {
  readonly account: UserResponse;
}

function AvatarUploadSection({ account }: AvatarUploadSectionProps): JSX.Element {
  const { t } = useTranslation(['account']);

  const getInitials = (): string => {
    const displayName = account.display_name?.trim();
    if (displayName) {
      return [...displayName][0]?.toLocaleUpperCase() ?? 'U';
    }

    const structuredInitials = [account.first_name, account.last_name]
      .flatMap((name) => (name?.trim() ? [[...name.trim()][0]?.toLocaleUpperCase()] : []))
      .join('');
    if (structuredInitials) {
      return structuredInitials;
    }

    return [...account.email][0]?.toLocaleUpperCase() ?? 'U';
  };

  return (
    <Card className="bg-muted/30">
      <CardHeader>
        <CardTitle>{t('account:sections.avatar.title')}</CardTitle>
        <CardDescription>{t('account:sections.avatar.description')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-6 sm:flex-row">
        <Avatar className="size-24 border-2 border-background shadow-sm">
          <AvatarFallback className="text-2xl">{getInitials()}</AvatarFallback>
        </Avatar>
        <div className="flex flex-col items-center gap-2 sm:items-start">
          <div className="flex items-center gap-2 text-muted-foreground text-sm italic">
            <ImagePlus className="size-4" />
            <span>{t('account:sections.avatar.placeholderMessage')}</span>
          </div>
          <p className="max-w-xs text-center text-muted-foreground text-xs sm:text-left">
            {t('account:sections.avatar.helpText')}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export { AvatarUploadSection };
